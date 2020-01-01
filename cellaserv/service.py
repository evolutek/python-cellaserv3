"""Service

The Service class allows you to write cellaserv services with high-level
decorators: Service.action and Service.event.

The @Service.action make a method exported to cellaserv. When matching request
is received, the method is called. The return value of the method is sent in
the reply. The return value must be json-encodable. The method must not take
too long to execute or it will cause cellaserv to send a RequestTimeout error
instead of your reply.

The @Service.event make the service listen for an event from cellaserv.

If you want to send requests to cellaserv, you should instanciate a
CellaservProxy object, see ``cellaserv.proxy.CellaservProxy``.

You can use ``self.publish('event_name')`` to send an event.

You can use ``self.log(...)`` to produce log entries for your service.

Example usage:

    >>> from cellaserv.service import Service
    >>> class Foo(Service):
    ...     @Service.action
    ...     async def bar(self):
    ...         print("bar")
    ...
    ...     @Service.event
    ...     async def on_foo(self):
    ...         print("foo")
    ...
    >>> s = Foo()
    >>> s.run()

Service life cycle
------------------

First, the service object is instantiated. At this point nothing happens
besides calling the class init method.

When the service loop is started, the service goes through a series of steps
after which it will be ready.

Service waits for dependencies.

Service receives configuration variables.

The Service.coro() tasks are started.

Service registers itself on cellaserv and becomes available to other cellaserv
client.

Service status
--------------

All service instance can set their "status" using self.status = "the service
status". Tools like the cellaserv dashboard can then query the service status
using the "list_variables" query of the service.

Starting more than one service
------------------------------

It is sometime preferable to start multiple services at the same time, for
example the same service but with different identifications. In this case you
will instantiate multiple services, then give control to the async loop with
Service.loop().

Example usage:

    >>> import asyncio
    >>> from cellaserv.service import Service
    >>> class Bar(Service):
    ...     def __init__(self, id):
    ...         super().__init__(identification=str(id))
    ...
    ...     @Service.action
    ...     async def bar(self):
    ...         print(self.identification)
    ...
    >>> Service.loop([Bar(i) for i in range(10)])

Dependencies
------------

You can specify that your service depends on another service using the
@Service.require('my_other_service') class decorator.

    >>> from cellaserv.service import Service
    >>> @Service.require('hokuyo')
    ... class WithDep(Service):
    ...     pass
    >>> # You can also specify a identification
    >>> @Service.require('hokuyo', identification='table')
    ... class WithDep2(Service):
    ...     pass

When the service is instantiated, it will wait for all the dependencies to be
registered on cellaserv.
"""

from collections import defaultdict
import asyncio
import functools
import inspect
import io
import json
import logging
import os
import sys
import threading
import time
import traceback

from google.protobuf.text_format import MessageToString

from cellaserv.protobuf.cellaserv_pb2 import (
    Message,
    Publish,
)

import cellaserv.settings
from cellaserv.client import Client

logger = logging.getLogger(__name__)
logger.setLevel(
    logging.DEBUG if cellaserv.settings.DEBUG >= 1 else logging.INFO)


def _request_to_string(req):
    """Dump request to a short string representation."""
    strfmt = (
        "{r.service_name}[{r.service_identification}].{r.method}({data}) "
        "#id={r.id}")
    return strfmt.format(r=req, data=req.data if req.data != b"" else "")


class Event:
    """
    Events help you share states between services.

    External clients can send data to the event in this service using a publish
    message to the event's name.

    Example::

        >>> from cellaserv.service import Service, Event
        >>> class Timer(Service):
        ...     event = Event()  # Sending a publish to "event" will set the event
        ...     ...
        ...     @Service.coro
        ...     async def coro_loop_wait(self):
        ...         while True:
        ...             await self.event.wait()
        ...             print("Waited! Event's data: ", self.event())
        ...             await asyncio.sleep(1)

    """
    def __init__(self, set=None, clear=None):
        """
        Define a new cellaserv Event.

        :param set str: Event that sets the variable
        :param clear str: Event that clears the variable
        """

        self.name = "?"  # set by Service to the name of the declared field
        # Optional data held by the event
        self.data = {}

        # Events that set/clear the event, if they are different from the name
        self._event_set = set
        self._event_clear = clear

        # Internal future object
        self._future = asyncio.Future()

    def wait(self):
        return self._future

    def is_set(self):
        return self._future.done()

    def set(self):
        self._future.set_result(self.data)

    def clear(self):
        old_future = self._future
        self._future = asyncio.Future()
        old_future.cancel()

    def __call__(self):
        """
        Returns the current value of the event.

        Handy syntactic sugar.
        """
        return self.data


class Variable:
    """
    Variables setups a cellaserv-exported variable for this service.

    Variable value updates are propagated using pubsub: on update, an event
    matching the variable name is published. The message must be a valid json
    object of the form: {'value': NEW VALUE}.

    Example::

        >>> from cellaserv.service import Service, Variable
        >>> class Foo(Service):
        ...     empty_var = Variable()
        ...     with_value = Variable("default_value")

    TODO: make ConfigVariable a child class of Variable
    """
    def __init__(self, default="", name=None):
        self._value = default
        self._name = name

    def __set_name__(self, owner, name):
        try:
            service_variables = getattr(owner, '_variables')
        except AttributeError:
            service_variables = {}
            setattr(owner, '_variables', service_variables)
        service_variables[name] = self
        self._name = name

    def __set__(self, service, value):
        self._update(value)
        service.publish(self._name, value=value)

    def __get__(self, instance, owner):
        del instance  # unused
        return self._value

    def _update(self, value):
        self._value = value

    def _set_name(self, name):
        self._name = name


class ConfigVariable:
    """
    ConfigVariable setup a variable using the 'config' service. It will always
    have the most up-to-date value.

    The value of this variable can be updated with the following event:
    'config.<section>.<option>'. The message must be a valid json object of the
    form: {'value': NEW VALUE}.

    Example::

        >>> from cellaserv.service import Service, ConfigVariable
        >>> class Match(Service):
        ...     color = ConfigVariable("match", "color")
        ...     ...

    You can also add callbacks to get notified when the variable is updated::

        >>> from cellaserv.service import Service, ConfigVariable
        >>> class Match(Service):
        ...     color = ConfigVariable("match", "color")
        ...     def __init__(self):
        ...         self.on_color_update() # set the self.color_coef
        ...         self.color.add_update_cb(self.on_color_update)
        ...     def on_color_update(self, value):
        ...         self.color_coef = 1 if value == "red" else -1
    """
    def __init__(self, section, option, coerc=str):
        """
        Define a new config variable using the 'config service'.

        :param section str: The section of this variable (eg. match, robot,
            etc.)
        :param option str: The option corresponding to this variable in the
            section.
        :param coerc function: The value will by passed to this function and
            the result will be the final value.
        """
        self.section = section
        self.option = option
        self.update_cb = []
        self.value = None
        self.coerc = coerc

    def add_update_cb(self, cb):
        """
        add_update_cb(cb) adds callback function that will be called when the
        value of the variable is updated.

        :param cb function: a function compatible with the prototype f(value)
        """
        self.update_cb.append(cb)

    def update(self, value):
        """
        update(value) is called when the value of the variable changes.

        NB. It is not called when the value is first set.
        """
        logger.debug("Variable %s.%s updated: %s", self.section, self.option,
                     value)
        self.value = self.coerc(value)
        for cb in self.update_cb:
            cb(self.value)

    def set(self, value):
        """set(value) is called when setting the value, not updating it."""
        self.value = self.coerc(value)

    def __call__(self):
        """
        Returns the current value of the variable.

        Handy syntactic sugar.
        """
        return self.value


class ServiceMeta(type):
    def __init__(cls, name, bases, nmspc):
        """
        ``__init__()`` is called when a new type of Service is created.

        This method setups the list of actions (cls._actions) and subscribed
        events (cls._event) in the new class.

        Basic level of metaprogramming magic.
        """
        def _event_wrap_set(event):
            async def _event_set(self, **kwargs):
                logger.debug("Event %s set, data=%s", event.name, kwargs)
                event.data = kwargs
                event.set()

            return _event_set

        def _event_wrap_clear(event):
            async def _event_clear(self, **kwargs):
                logger.debug("Event %s cleared, data=%s", event.name, kwargs)
                event.data = kwargs
                event.clear()

            return _event_clear

        def _config_var_wrap_event(variable):
            async def _variable_update(self, value):
                variable.update(value=value)

            return _variable_update

        actions = {}
        config_variables = []
        events = {}
        coros = []
        service_dependencies = set()

        # Go through all the members of the class, check if they are tagged as
        # action, events, etc. Wrap them if necessary then store them in lists.
        for name, member in inspect.getmembers(cls):
            if hasattr(member, "_actions"):
                for action in member._actions:
                    actions[action] = member
            elif hasattr(member, "_events"):
                for event in member._events:
                    events[event] = member
            elif hasattr(member, "_coro"):
                coros.append(member)

            elif isinstance(member, ConfigVariable):
                event_name = "config.{section}.{option}".format(
                    section=member.section, option=member.option)
                events[event_name] = _config_var_wrap_event(member)
                config_variables.append(member)
                # Ensure config is a dependency for this service
                service_dependencies.add(("config", ""))

            elif isinstance(member, Event):
                member.name = name
                event_set = member._event_set or name
                event_clear = member._event_clear or name + "_clear"
                events[event_set] = _event_wrap_set(member)
                events[event_clear] = _event_wrap_clear(member)

        cls._actions = actions
        cls._config_variables = config_variables
        cls._events = events
        cls._coros = coros
        cls._service_dependencies = service_dependencies

        return super().__init__(cls)


class Service(Client, metaclass=ServiceMeta):

    # Mandatory name of the service as it will appeared for cellaserv.
    service_name = None
    # Optional identification string used to register multiple instances of the
    # same service.
    identification = ""

    # Service status
    status = Variable("Not ready")

    def __init__(self, identification=""):
        super().__init__()

        if not self.service_name:
            # service name is class name in lower case
            self.service_name = self.__class__.__name__.lower()

        self.identification = identification or self.identification or ""

        loop = asyncio.get_event_loop()
        loop.create_task(self._setup())
        self._loop = loop

    # Protocol helpers

    @classmethod
    def _decode_msg_data(kls, msg):
        """Returns the data contained in a message."""
        if msg.data:
            return kls._decode_data(msg.data)
        else:
            return {}

    @staticmethod
    def _decode_data(data):
        """Returns the data contained in a message."""
        try:
            obj = data.decode()
            return json.loads(obj)
        except (UnicodeDecodeError, ValueError):
            # In case the data cannot be decoded, return raw data.
            # This "feature" can be used to communicate with services that
            # don't handle json data, but only raw bytes.
            return data

    # Class decorators

    @classmethod
    def require(cls, service, identification=""):
        """
        Use the ``Service.require`` class decorator to specify a dependency
        between this service and ``service``. This service will not start
        before the ``service`` service is registered on cellaserv.
        """

        depend = (service, identification)

        def class_builder(cls):
            cls._service_dependencies.add(depend)

            return cls

        return class_builder

    # Methods decorators

    @staticmethod
    def action(method_or_name):
        """
        Use the ``Service.action`` decorator on a method to declare it as
        exported to cellaserv. If a parameter is given, change the name of the
        method to that name.

        :param name str: Change the name of that method to ``name``.
        """
        def _set_action(method, action):
            try:
                method._actions.append(action)
            except AttributeError:
                method._actions = [action]

            return method

        def _wrapper(method):
            return _set_action(method, method_or_name)

        if callable(method_or_name):
            return _set_action(method_or_name, method_or_name.__name__)
        else:
            return _wrapper

    @staticmethod
    def event(method_or_name):
        """
        The method decorated with ``Service.event`` will be called when a event
        matching its name (or argument passed to ``Service.event``) is
        received.
        """
        def _set_event(method, event):
            try:
                method._events.append(event)
            except AttributeError:
                method._events = [event]

            return method

        def _wrapper(method):
            return _set_event(method, method_or_name)

        if callable(method_or_name):
            return _set_event(method_or_name, method_or_name.__name__)
        else:
            return _wrapper

    @staticmethod
    def coro(method):
        """
        The method decorated with ``Service.coro`` will be started after
        the Service is registered and fully initialized.

        Example::

            >>> from cellaserv.service import Service
            >>> from time import sleep
            >>> class Foo(Service):
            ...     @Service.coro
            ...     async def loop(self):
            ...         while True:
            ...             print("hello!")
            ...             await asyncio.sleep(1)
        """

        method._coro = True
        return method

    @classmethod
    def loop(kls, services):
        """Wait for multiple services."""
        loop = asyncio.get_event_loop()
        loop.run_until_complete(kls._loop(services))
        loop.close()

    @classmethod
    async def _loop(kls, services):
        await asyncio.wait([service.done() for service in services])

    # Instantiated class land
    async def done(self):
        await self._disconnect

    async def on_request(self, req):
        """
        on_request(req) is called when a request is received by the service.
        """
        if req.service_identification != self.identification:
            logger.error("Dropping request for wrong identification")
            return

        method = req.method

        try:
            callback = self._actions[method]
        except KeyError:
            logger.error("No such method: %s.%s", self, method)
            self.reply_error_to(req, cellaserv.client.Reply.Error.NoSuchMethod,
                                method)
            return

        try:
            data = self._decode_msg_data(req)
        except Exception as e:
            logger.error("Bad arguments formatting: %s",
                         _request_to_string(req),
                         exc_info=True)
            self.reply_error_to(req, cellaserv.client.Reply.Error.BadArguments,
                                req.data)
            return

        try:
            logger.debug("Calling %s/%s.%s(%s)...", self.service_name,
                         self.identification, method, data)

            # Guess type of arguments passing
            if type(data) is list:
                args = data
                kwargs = {}
            elif type(data) is dict:
                args = []
                kwargs = data
            else:
                args = [data]
                kwargs = {}

            # We use the descriptor's __get__ because we don't know if the
            # callback should be bound to this instance.
            bound_cb = callback.__get__(self, type(self))
            reply_data = await bound_cb(*args, **kwargs)
            logger.debug("Called %s/%s.%s(%s) = %s", self.service_name,
                         self.identification, method, data, reply_data)
            # Method may, or may not return something. If it returns some data,
            # it must be encoded in json.
            if reply_data is not None:
                reply_data = json.dumps(reply_data).encode()
        except Exception as e:
            self.reply_error_to(req, cellaserv.client.Reply.Error.Custom,
                                str(e))
            logger.error("Exception during %s",
                         _request_to_string(req),
                         exc_info=True)
            return

        self.reply_to(req, reply_data)

    # Default actions
    async def help(self) -> dict:
        """
        Help about this service.

        TODO: refactor all help functions, compute help dicts when creating the
        class using metaprogramming.
        """
        docs = {}
        docs["doc"] = inspect.getdoc(self)
        docs["actions"] = await self.help_actions()
        docs["events"] = await self.help_events()
        docs["variables"] = await self.help_variables()
        return docs

    help._actions = ["help"]

    def _get_help(self, methods) -> dict:
        """
        Helper function that create a dict with the signature and the
        documentation of a mapping of methods.
        """
        docs = {}
        for name, unbound_f in methods.items():
            # Get the function from self to get a bound method in order to
            # remove the first parameter (class name).
            bound_f = unbound_f.__get__(self, type(self))
            doc = inspect.getdoc(bound_f) or ""

            # Get signature of this method, ie. how the user must call it
            if sys.version_info.minor < 3:
                sig = (name +
                       inspect.formatargspec(*inspect.getfullargspec(bound_f)))
            else:
                sig = name + str(inspect.signature(bound_f))

            docs[name] = {"doc": doc, "sig": sig}
        return docs

    async def help_actions(self) -> dict:
        """List available actions for this service."""
        return self._get_help(self._actions)

    help_actions._actions = ["help_actions"]

    async def help_events(self) -> dict:
        """List subscribed events of this service."""
        return self._get_help(self._events)

    help_events._actions = ["help_events"]

    async def list_variables(self) -> dict:
        """List variables of this service."""
        ret = {}
        for variable in self._variables.values():
            ret[variable._name] = variable._value
        return ret

    list_variables._actions = ["list_variables"]

    # Note: we cannot use @staticmethod here because the descriptor it creates
    # is shadowing the attribute we add to the method.
    async def kill(self) -> "Does not return.":
        """Kill the service."""
        self._disconnect.set_result(True)

    kill._actions = ["kill"]

    async def stacktraces(self) -> dict:
        """Return a stacktrace for each thread running."""
        ret = {}
        for thread_id, stack in sys._current_frames().items():
            ret[thread_id] = "\n".join(traceback.format_stack(stack))
        return ret

    stacktraces._actions = ["stacktraces"]

    # Convenience methods

    def log(self, *args, what=None, **log_data):
        """
        Send a log message to cellaserv using the service's name and
        identification, if any. ``what`` is an optional topic for the log. If
        provided, it will we append to the log name.

        Logs in cellaserv are implemented using event with the form
        ``log.<service_name>.<optional service_ident>.<optional what>``.
        """
        log_name = "log." + self.service_name

        if self.identification:
            log_name += "." + self.identification

        if what:
            log_name += "." + what

        if args:
            # Emulate a call to print()
            out = io.StringIO()
            print(*args, end="", file=out)
            out.seek(0)
            log_data["msg"] = out.read().decode()

        # Publish log message to cellaserv
        self.publish(event=log_name, **log_data)

    # Main setup of the service

    async def _setup(self):
        """
        _setup() will use the socket connected to cellaserv to initialize the
        service.
        """
        # Start accepting messages
        asyncio.create_task(self.handle_messages())
        await self._connected

        await self._wait_for_dependencies()
        await self._setup_variables()
        await self._setup_config_vars()
        await self._setup_events()

        await self.register(self.service_name, self.identification)

        await self._start_coros()

        logger.info("Service running!")

    async def _setup_config_vars(self):
        """
        setup_synchronous manages the static initialization of the service.
        When this methods return, the service should be fully functional.

        What needs to be synchronously setup:

        - dependencies, that is we have to wait for them to be online,
        - configuration variables should have the default value.
        """

        for variable in self._config_variables:
            req_data = {"section": variable.section, "option": variable.option}
            req_data_bytes = json.dumps(req_data).encode()
            # Send the request
            data = await self.request("get", "config", data=req_data_bytes)
            # Data is json encoded
            args = self._decode_data(data)
            logger.info("[ConfigVariable] %s.%s is %s", variable.section,
                        variable.option, args)
            # we don't use update() because the context of the service is
            # not yet initialized, and it is not an update of a previous
            # value (because there isn't)
            variable.set(args)

    async def _wait_for_dependencies(self):
        """
        Wait for all dependencies.
        """

        if not self._service_dependencies:
            # No dependencies, return early
            return

        # Create a special client for dependency setup only
        class DependencyWaitingClient(Client):
            def __init__(self, dependencies):
                super().__init__()

                self._services_missing = dependencies
                self._services_missing_lck = asyncio.Lock()
                self._all_services_present = asyncio.Future()

            async def wait_for_dependencies(self):
                # Ensure the client loop is started
                asyncio.create_task(self._read_messages())

                # First register for new services, so that we don't miss a service
                # if it registers just after the 'list_services' call.
                self.subscribe("log.cellaserv.new-service",
                               self._check_service)

                asyncio.create_task(self.heartbeat())
                await self._backlog()
                await self._all_services_present

            async def _backlog(self):
                # Get the list of already registered service.
                data = await self.request("list_services", "cellaserv")
                services_registered = json.loads(data)

                for service in services_registered:
                    await self._check_service(service["name"],
                                              service["identification"])

            async def _check_service(self, name, identification, client=None):
                key = (name, identification)
                try:
                    self._services_missing.remove(key)
                except KeyError:
                    # Not waiting for this service
                    return
                logger.info("Waited for %s", key)
                if len(self._services_missing) == 0:
                    self._all_services_present.set_result(None)

            async def heartbeat(self):
                while not self._all_services_present.done():
                    logger.info("Waiting for %s", self._services_missing)
                    await asyncio.sleep(1)

        client = DependencyWaitingClient(self._service_dependencies)
        await client.connect()
        self.status = "Waiting for dependencies: {}".format(
            self._service_dependencies)
        await client.wait_for_dependencies()
        self.status = "Ready"

    async def _setup_variables(self):
        """
        Setup variables.
        """
        def _var_wrap_set(variable):
            async def _var_set(self, value):
                variable._update(value)

            return _var_set

        for var_name, variable in self._variables.items():
            # Prefix the variable name with the service name
            fq_var_name = self.service_name
            if self.identification:
                fq_var_name += "." + self.identification
            fq_var_name += "." + var_name
            variable._set_name(fq_var_name)
            self._events[fq_var_name] = _var_wrap_set(variable)

    async def _setup_events(self):
        """
        Subscribe to events.
        """
        for event_name, callback in self._events.items():
            # Bind method to object
            callback_bound = callback.__get__(self, type(self))
            self.subscribe(event_name, callback_bound)

    async def _start_coros(self):
        """Schedules services coroutines."""
        for method in self._coros:
            # Bind method to the current instance
            bound_method = method.__get__(self, type(self))
            asyncio.create_task(bound_method())

    def run(self):
        """
        Sugar for starting the service with asyncio.
        """
        self._loop.run_forever()
        self._loop.close()
