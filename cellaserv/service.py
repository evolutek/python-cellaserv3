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

import asyncio
import inspect
import io
import json
import logging
import sys
import traceback

import cellaserv.settings
from cellaserv.client import Client

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if cellaserv.settings.DEBUG >= 1 else logging.INFO)


def _request_to_string(req):
    """Dump request to a short string representation."""
    strfmt = (
        "{r.service_name}[{r.service_identification}].{r.method}({data}) " "#id={r.id}"
    )
    return strfmt.format(r=req, data=req.data if req.data != b"" else "")


class Event:
    """
    Events help you share states between services.

    External clients can send data to the event in this service using a publish
    message to the event's name.

    Usage::

        >>> class Foo(Service):
        ...     myevent = Event()
        ...
        ...     @Service.coro
        ...     async def my_coro(self):
        ...         # Wait for event to be set
        ...         await self.myevent.wait()
        ...         # Read data attached to event
        ...         print(self.myevent.data)
        ...         # Wait for event to be cleared
        ...         await self.myevent.wait_clear()
        ...         # Set an event named "foo"
        ...         self.set_event("foo")
    """

    def __init__(self, set=None, clear=None):
        """
        Define a new cellaserv Event.

        :param set str: Event that sets the variable
        :param clear str: Event that clears the variable
        """

        self._name = None
        self._data = None

        # Events that set/clear the event, if they are different from the name
        self._event_set = set
        self._event_clear = clear

        # Not initialized here because the event loop may not be ready yet
        self._set_event = None
        self._clear_event = None
        # Cellaserv client
        self._client = None

    def __set_name__(self, service, name):
        try:
            events = getattr(service, "_event_attributes")
        except AttributeError:
            events = []
            setattr(service, "_event_attributes", events)
        events.append(self)

        self._name = name
        self._event_set = self._event_set or name
        self._event_clear = self._event_clear or f"{name}_clear"

    def async_init(self, client):
        """Initializes the event with the current event loop."""
        self._set_event = asyncio.Event()
        self._clear_event = asyncio.Event()
        self._client = client

    @property
    def event_set(self):
        return self._event_set

    @property
    def event_clear(self):
        return self._event_clear

    async def wait_set(self):
        await self._set_event.wait()

    async def wait_clear(self):
        await self._clear_event.wait()

    def is_set(self):
        return self._set_event.is_set()

    async def set(self, *args, **kwargs):
        if args:
            self._client.publish(self.event_set, *args)
        else:
            self._client.publish(self.event_set, **kwargs)
        await self.wait_set()

    async def clear(self):
        self._client.publish(self.event_clear)
        await self.wait_clear()

    def on_set(self, *args, **kwargs):
        logger.debug("Event %s set, args=%s kwargs=%s", self._name, args, kwargs)
        self._data = args or kwargs
        self._set_event.set()
        self._clear_event.clear()

    def on_clear(self):
        logger.debug("Event %s cleared", self._name)
        self._data = None
        self._set_event.clear()
        self._clear_event.set()

    def data(self):
        return self._data


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
        ...     foo_var = Variable(name="different_variable_name")
    """

    def __init__(self, default="", name=None, coerc=None):
        """
        Define a new variable defined using the "config" service.

        :param coerc function: The value will by passed to this function and
            the result will be the final value.
        """
        self._value = default
        self._name = name
        self._coerc = coerc

        # Callbacks called when the variable is updated
        self._on_update_cb = []

    def __set_name__(self, service, name):
        service.register_variable(self, name)

    def __set__(self, service, value):
        self.update(value)
        service.publish(self._name, value=value)

    def __get__(self, instance, owner):
        return self._value

    @property
    def name(self):
        return self._name

    def has_name(self):
        return self._name is not None

    def set_name(self, name):
        self._name = name

    def update(self, value):
        if self._coerc:
            value = self._coerc(value)
        self._value = value
        for cb in self._on_update_cb:
            cb(self._value)

    def add_update_cb(self, cb):
        self._on_update_cb.append(cb)

    def on_update(self, cb):
        """
        Decorator. The `cb` function will be called when the variable is
        updated.

        :param cb function: a function compatible with the prototype f(value)
        """
        # Cannot use `self.add_update_cb(cb)` because `cb` is an unbound
        # function.
        if hasattr(cb, "_on_update_variables"):
            cb._on_update_variables.append(self)
        else:
            cb._on_update_variables = [self]
        return cb

    def asdict(self):
        return {"name": self._name, "value": self._value}


class ConfigVariable(Variable):
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
        ...         self.color_coef = None
        ...
        ...     @color.on_update
        ...     def on_color_update(self, value):
        ...         self.color_coef = 1 if value == "red" else -1
    """

    def __init__(self, section, option, coerc=None):
        """
        Define a new config variable using the 'config service'.

        :param section str: The section of this variable (eg. match, robot,
            etc.)
        :param option str: The option corresponding to this variable in the
            section.
        :param coerc function: The value will by passed to this function and
            the result will be the final value.
        """
        self._section = section
        self._option = option
        super().__init__(name=f"config.{section}.{option}", coerc=coerc)

    def __set_name__(self, service, name):
        super().__set_name__(service, name)
        service.register_config_variable(self)

    def __set__(self, service, value):
        raise TypeError("Cannot set a config variable.")

    async def fetch_value(self, client):
        data = await client.request(
            "get", "config", data={"section": self._section, "option": self._option}
        )
        logger.info("[ConfigVariable] %s.%s is %s", self._section, self._option, data)
        self.update(data)


class ServiceMeta(type):
    @classmethod
    def __prepare__(metacls, *args, **kwargs):
        namespace = super().__prepare__(*args, **kwargs)
        # Populate namespace so that class-scoped variables like Variables can
        # modify the type.
        namespace["_variables"] = []
        namespace["_config_variables"] = []
        return namespace


class Service(Client, metaclass=ServiceMeta):
    @classmethod
    def register_variable(service, variable, var_name):
        service._variables.append([variable, var_name])

    @classmethod
    def register_config_variable(service, config_variable):
        service._config_variables.append(config_variable)

    def __init__(self, identification=""):
        super().__init__()

        # service name is class name in lower case
        self.service_name = self.__class__.__name__.lower()
        self.identification = identification

        self._init_smart_attributes()

        # The client has finished the setup phase.
        self._ready = asyncio.Future()

        asyncio.create_task(self._async_init())

    def _init_smart_attributes(self):
        actions = {}
        events = {}
        coros = []
        service_dependencies = set()

        # Go through all the members of the class, check if they are tagged as
        # action, events, etc. Wrap them if necessary then store them in lists.
        for name, member in inspect.getmembers(self):
            if hasattr(member, "_actions"):
                for action in member._actions:
                    actions[action] = member
            elif hasattr(member, "_events"):
                for event in member._events:
                    events[event] = member
            elif hasattr(member, "_service_coro"):
                coros.append(member)
            elif hasattr(member, "_on_update_variables"):
                for variable in member._on_update_variables:
                    variable.add_update_cb(member)

        # TODO: move that before and avoid the local variables
        self._actions = actions
        self._events = events
        self._coros = coros
        self._service_dependencies = service_dependencies

        if not hasattr(self, "_event_attributes"):
            self._event_attributes = []

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
            if hasattr(cls, "_service_dependencies"):
                cls._service_dependencies.add(depend)
            else:
                cls._service_dependencies = {depend}
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

        # Note: `_coro` is already used by asyncio.Task objects
        method._service_coro = True
        return method

    # Instantiated class land

    def done(self):
        return self._disconnected

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
            await self.reply_error_to(
                req, cellaserv.client.Reply.Error.NoSuchMethod, method
            )
            return

        try:
            if req.data != b"":
                data = json.loads(req.data.decode())
            else:
                data = None
        except Exception:
            logger.error(
                "Bad arguments formatting: %s", _request_to_string(req), exc_info=True
            )
            await self.reply_error_to(
                req, cellaserv.client.Reply.Error.BadArguments, req.data
            )
            return

        try:
            logger.debug(
                "Calling %s/%s.%s(%s)...",
                self.service_name,
                self.identification,
                method,
                data,
            )

            # Guess type of arguments
            if type(data) is list:
                args = data
                kwargs = {}
            elif type(data) is dict:
                args = []
                kwargs = data
            else:
                args = []
                kwargs = {}

            if inspect.iscoroutinefunction(callback):
                reply_data = await callback(*args, **kwargs)
            else:
                reply_data = callback(*args, **kwargs)

            logger.debug(
                "Called %s/%s.%s(%s) = %s",
                self.service_name,
                self.identification,
                method,
                data,
                reply_data,
            )
            # Method may, or may not return something. If it returns some data,
            # it must be encoded in json.
            if reply_data is not None:
                reply_data = json.dumps(reply_data).encode()
        except Exception as e:
            await self.reply_error_to(req, cellaserv.client.Reply.Error.Custom, str(e))
            logger.error("Exception during %s", _request_to_string(req), exc_info=True)
            return

        await self.reply_to(req, reply_data)

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
        docs["variables"] = await self.list_variables()
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
                sig = name + inspect.formatargspec(*inspect.getfullargspec(bound_f))
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
        ret = []
        for variable, _ in self._variables:
            ret.append(variable.asdict())
        return ret

    list_variables._actions = ["list_variables"]

    # Note: we cannot use @staticmethod here because the descriptor it creates
    # is shadowing the attribute we add to the method.
    async def kill(self):
        """Kill the service."""
        await self.disconnect()

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
            log_data["msg"] = out.read()

        # Publish log message to cellaserv
        self.publish(event=log_name, **log_data)

    # Main setup of the service

    async def _async_init(self):
        """Initializes the service."""
        await self.connected()

        await self._setup_variables()
        await self._setup_events()
        await self._wait_for_dependencies()
        await self._setup_config_vars()

        await self.register(self.service_name, self.identification)

        await self._start_coros()

        logger.info("Service running!")
        self._ready.set_result(True)

    async def ready(self):
        await self._ready

    async def _setup_config_vars(self):
        if self._config_variables:
            await asyncio.wait(
                {variable.fetch_value(self) for variable in self._config_variables}
            )

    async def _wait_for_dependencies(self):
        """
        Wait for all dependencies.
        """
        if self._config_variables:
            self._service_dependencies.add(("config", ""))

        if not self._service_dependencies:
            # No dependencies, return early
            return

        super_done = self.done()

        # Create a special client for dependency setup only
        class DependencyWaitingClient(Client):
            def __init__(self, dependencies):
                super().__init__()

                self._services_missing = dependencies
                self._all_services_present = asyncio.Future()

            async def wait_for_dependencies(self):
                # First register for new services, so that we don't miss a service
                # if it registers just after the 'list_services' call.
                await self.subscribe("log.cellaserv.new-service", self._check_service)

                await self._process_backlog()
                await self._active_wait()

            async def _process_backlog(self):
                # Get the list of already registered service.
                services_registered = await self.request("list_services", "cellaserv")

                for service in services_registered:
                    await self._check_service(
                        service["name"], service["identification"]
                    )

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

            async def _active_wait(self):
                while True:
                    logger.info("Waiting for %s", self._services_missing)
                    try:
                        await asyncio.wait_for(
                            asyncio.wait(
                                {self._all_services_present, super_done},
                                return_when=asyncio.FIRST_COMPLETED,
                            ),
                            timeout=1,
                        )
                    except asyncio.TimeoutError:
                        continue
                    if super_done.done() or self._all_services_present.done():
                        break

        client = DependencyWaitingClient(self._service_dependencies)
        await client.connected()
        await client.wait_for_dependencies()
        await client.disconnect()

    async def _setup_variables(self):
        for variable, var_name in self._variables:
            if not variable.has_name():
                # Prefix the variable name with the service name
                fq_var_name = self.service_name
                if self.identification:
                    fq_var_name += "." + self.identification
                fq_var_name += "." + var_name
                variable.set_name(fq_var_name)
            self._events[variable.name] = variable.update

    async def _setup_events(self):
        """
        Subscribe to events.
        """
        for event in self._event_attributes:
            event.async_init(client=self)
            await self.subscribe(event.event_set, event.on_set)
            await self.subscribe(event.event_clear, event.on_clear)
        for event_name, callback in self._events.items():
            # Bind method to object
            callback_bound = callback.__get__(self, type(self))
            await self.subscribe(event_name, callback_bound)

    async def _start_coros(self):
        """Schedules services coroutines."""
        for method in self._coros:
            asyncio.create_task(method())
