"""Service

The Service class allows you to write cellaserv services with high-level
decorators: Service.action and Service.event.

The @Service.action make a method exported to cellaserv. When matching request
is received, the method is called. The return value of the method is sent in
the reply. The return value must be json-encodable. The method must not take
too long to execute or it will cause cellaserv to send a RequestTimeout error
instead of your reply.

The @Service.event make the service listen for an event from cellaserv.

If you want to send requests to cellaserv from within a service, used `self.cs`
to access a `CellaservProxy` instance.

You can use ``self.publish('event_name')`` to send an event.

You can use ``self.log(...)`` to produce log entries for your service.

Example usage:

    >>> import asyncio
    >>> from cellaserv.service import Service
    >>> class Foo(Service):
    ...     @Service.action
    ...     def bar(self):
    ...         print("bar")
    ...
    ...     @Service.event
    ...     async def on_foo(self):
    ...         await asyncio.sleep(1)
    ...
    >>> s = Foo()
    >>> asyncio.run(s.done())

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
from collections import defaultdict
from typing import Any, Callable

import cellaserv.settings
from cellaserv.client import Client
from cellaserv.proxy import CellaservProxy

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

    def __init__(
        self, name: str = None, set_event: str = None, clear_event: str = None
    ):
        """
        Define a new cellaserv Event.

        :param set str: Event that sets the variable
        :param clear str: Event that clears the variable
        """
        self._name = name
        self._set_event = set_event
        self._clear_event = clear_event

    @property
    def name(self) -> str:
        return self._name

    @property
    def set_event(self) -> None:
        return self._set_event

    @property
    def clear_event(self) -> None:
        return self._clear_event

    async def wait_set(self) -> None:
        raise NotImplementedError

    async def wait_clear(self) -> None:
        raise NotImplementedError

    def is_set(self) -> bool:
        raise NotImplementedError

    async def set(self, *args, **kwargs) -> None:
        raise NotImplementedError

    async def clear(self) -> None:
        raise NotImplementedError

    def on_event_set(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def on_event_clear(self) -> None:
        raise NotImplementedError

    def data(self) -> Any:
        raise NotImplementedError

    def per_instance(self, name, client):
        name = self.name or name
        set_event = self.set_event or name
        clear_event = self.clear_event or f"{name}_clear"
        return EventPerInstance(
            name=name, set_event=set_event, clear_event=clear_event, client=client
        )


class EventPerInstance(Event):
    """Implementation the Event object when used in a Service."""

    def __init__(self, name: str, set_event: str, clear_event: str, client: Client):
        super().__init__(name=name, set_event=set_event, clear_event=clear_event)
        self._client = client

        # Internal state
        self._event_set = asyncio.Event()
        self._event_clear = asyncio.Event()
        self._data: Any = None

    async def wait_set(self):
        await self._event_set.wait()

    async def wait_clear(self):
        await self._event_clear.wait()

    def is_set(self):
        return self._event_set.is_set()

    async def set(self, *args, **kwargs):
        self._client.publish(self._set_event, *args, **kwargs)
        await self.wait_set()

    async def clear(self):
        self._client.publish(self._clear_event)
        await self.wait_clear()

    def on_event_set(self, *args, **kwargs):
        logger.debug("Event %s set, args=%s kwargs=%s", self._name, args, kwargs)
        self._data = args or kwargs
        self._event_set.set()
        self._event_clear.clear()

    def on_event_clear(self):
        logger.debug("Event %s cleared", self._name)
        self._data = None
        self._event_set.clear()
        self._event_clear.set()

    def data(self):
        return self._data


class Variable:
    """
    Variables setups a cellaserv-exported variable for this service.

    Variable value updates are propagated using pubsub: on update, an event
    matching the variable name is published. The message must be a valid json
    object of the form: {'value': Any}.

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
        :param service str: name of a service to get the initial value of the
            variable from.
        """
        self._value = default
        self._name = name
        self._coerc = coerc

    @property
    def name(self) -> str:
        return self._name

    @property
    def data(self) -> Any:
        return self._value

    @property
    def coerc(self) -> Callable[[str], Any]:
        return self._coerc

    def on_update(self, cb):
        """
        Decorator. The `cb` function will be called when the variable is
        updated.

        :param cb function: a function compatible with the prototype f(value)
        """
        if hasattr(cb, "_on_update_variables"):
            cb._on_update_variables.append(self)
        else:
            cb._on_update_variables = [self]
        return cb

    def per_instance(self, name, service):
        # Compute variable name
        if self.name:
            var_name = self.name
        else:
            # Prefix the variable name with the service name
            var_name = service.service_name
            if service.identification:
                var_name += "." + service.identification
            var_name += "." + name
        return VariablePerInstance(
            default=self.data, name=var_name, coerc=self.coerc, client=service
        )


class VariablePerInstance(Variable):
    def __init__(self, client: Client, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = client

        # Callbacks called when the variable is updated
        self._on_update_cb = []

    # Note: cannot use __get__ / __set__ because the descriptor protocol
    # requires them to be on classes, and they cannot be instances.
    def set(self, value):
        self.update(value)
        self._client.publish(self._name, value=value)

    def get(self):
        return self._value

    def update(self, value):
        if self._coerc:
            value = self._coerc(value)
        self._value = value
        for cb in self._on_update_cb:
            cb(self._value)

    def add_update_cb(self, cb):
        self._on_update_cb.append(cb)

    def asdict(self):
        return {"name": self._name, "value": self._value}

    async def fetch_value(self):
        pass


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
        super().__init__(name=f"config.{section}.{option}", coerc=coerc)

        self._section = section
        self._option = option

    def per_instance(self, name, service):
        del name  # unused
        return ConfigVariablePerInstance(
            default=self.data,
            name=self.name,
            coerc=self.coerc,
            option=self._option,
            section=self._section,
            client=service,
        )


class ConfigVariablePerInstance(VariablePerInstance):
    def __init__(self, option, section, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._option = option
        self._section = section

    async def fetch_value(self):
        """Reads the variable value from the "config" service."""
        data = await self._client.request(
            "get", "config", data={"section": self._section, "option": self._option}
        )
        logger.info("[ConfigVariable] %s.%s is %s", self._section, self._option, data)
        self.update(data)


class Service(Client):
    def __init__(self, identification=""):
        super().__init__()

        # service name is class name in lower case
        self.service_name = self.__class__.__name__.lower()
        self.identification = identification

        self._actions = {}
        self._events = {}
        self._coros = []
        self._variables = []
        self._service_dependencies = set()

        # The client has finished the setup phase.
        self._ready = asyncio.Event()

        # Init in _async_init()
        self.cs = CellaservProxy(self)

        asyncio.create_task(self._async_init())

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

    async def done(self):
        await self._disconnected.wait()

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

    def get_events(self) -> dict:
        """List events subscribed by this service."""
        return [str(key) for key in self._events.keys()]

    get_events._actions = ["get_events"]

    def get_variables(self) -> dict:
        """List variables of this service."""
        ret = []
        for variable in self._variables:
            ret.append(variable.asdict())
        return ret

    get_variables._actions = ["get_variables"]

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

        await self._init_actions()
        await self._init_variables()
        await self._init_events()
        await self._wait_for_dependencies()
        await self._init_variables_values()

        await self.register(self.service_name, self.identification)

        await self._start_coros()

        logger.info("Service running!")
        self._ready.set()

    def _getmembers(self):
        for name, member in inspect.getmembers(self):
            # Filter CellaservProxy out because it implements a catchall
            # __getattr__ which does not play well with hasttr()
            if isinstance(member, CellaservProxy):
                continue
            yield name, member

    async def ready(self):
        await self._ready.wait()

    async def _wait_for_dependencies(self):
        """
        Wait for all dependencies.
        """
        if not self._service_dependencies:
            # No dependencies, return early
            return

        super_done = self._disconnected

        # Create a special client for dependency setup only
        class DependencyWaitingClient(Client):
            def __init__(self, dependencies):
                super().__init__()

                self._services_missing = dependencies
                self._all_services_present = asyncio.Event()

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
                    self._all_services_present.set()

            async def _active_wait(self):
                while True:
                    logger.info("Waiting for %s", self._services_missing)
                    try:
                        await asyncio.wait_for(
                            asyncio.wait(
                                {self._all_services_present.wait(), super_done.wait()},
                                return_when=asyncio.FIRST_COMPLETED,
                            ),
                            timeout=1,
                        )
                    except asyncio.TimeoutError:
                        continue
                    if super_done.is_set() or self._all_services_present.is_set():
                        break

        client = DependencyWaitingClient(self._service_dependencies)
        await client.connected()
        await client.wait_for_dependencies()
        await client.disconnect()

    async def _init_actions(self):
        for name, member in self._getmembers():
            if hasattr(member, "_actions"):
                for action in member._actions:
                    self._actions[action] = member

    async def _init_variables(self):
        update_callbacks = defaultdict(list)

        # Collect update callbacks
        for _, member in self._getmembers():
            if not hasattr(member, "_on_update_variables"):
                continue

            for var_desc in member._on_update_variables:
                update_callbacks[var_desc].append(member)

        # Setup variables
        for name, member in self._getmembers():
            if not isinstance(member, Variable):
                continue
            if isinstance(member, ConfigVariable):
                # Special case for config variables
                self._service_dependencies.add(("config", ""))
            # Re-instanciate the variable for this service
            variable = member.per_instance(name, self)
            # Replace descriptor with instanciated version
            setattr(self, name, variable)
            await self.subscribe(variable.name, variable.on_update)
            # Add callbacks
            for callback in update_callbacks[member]:
                variable.add_update_cb(callback)
            # Collect variable
            self._variables.append(variable)

    async def _init_variables_values(self):
        aws = {variable.fetch_value() for variable in self._variables}
        if aws:
            await asyncio.wait(aws)

    async def _init_events(self):
        """
        Subscribe to events.
        """
        # Process Event()-defined events
        for name, member in self._getmembers():
            if not isinstance(member, Event):
                continue
            event = member.per_instance(name, self)
            # Replace event descriptor with event implementation for this
            # instance of the service
            setattr(self, name, event)

            await self.subscribe(event.set_event, event.on_event_set)
            await self.subscribe(event.clear_event, event.on_event_clear)

        # Process @Service.event-defined events
        for name, member in self._getmembers():
            if not hasattr(member, "_events"):
                continue
            for event_name in member._events:
                await self.subscribe(event_name, member)

    async def _start_coros(self):
        """Schedules services coroutines."""
        for name, member in self._getmembers():
            if not hasattr(member, "_service_coro"):
                continue
            asyncio.create_task(member())
