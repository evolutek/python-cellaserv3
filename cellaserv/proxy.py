"""Proxy object for cellaserv.

Data for requests and events is encoded as JSON objects.

Example usage::

    >>> import asyncio
    >>> from cellaserv.proxy import CellaservProxy
    >>> async def run():
    ...     robot = CellaservProxy()
    ...     await robot.connect()
    ...     # Make a query
    ...     await robot.date.time()
    ...     # Send event 'match-start'
    ...     robot('match-start')
    ...     # Send event 'wait' with data
    ...     robot('wait', seconds=2)
    >>> asyncio.run(run())
"""

import asyncio
import json
import logging
import traceback

from cellaserv.client import Client
from cellaserv.settings import DEBUG

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if DEBUG >= 2 else logging.INFO if DEBUG ==
                1 else logging.WARNING)


class ActionProxy:
    """Action proxy for cellaserv."""
    def __init__(self, action, service, identification, client):
        self._action = action
        self._service = service
        self._identification = identification
        self._client = client

    async def _json_loads(self, reply_future):
        return json.loads(await reply_future)

    def __call__(self, *args, **kwargs):
        if args and kwargs:
            logger.error(
                "[Proxy] Cannot send a request with both args and kwargs")
            str_stack = ''.join(traceback.format_stack())
            self._client.publish(event='log.error', data=str_stack.encode())
            return None

        data = args or kwargs
        req_data = json.dumps(data).encode() if data else None
        reply_future = self._client.request(
            self._action,
            service=self._service,
            identification=self._identification,
            data=req_data)
        return self._json_loads(reply_future)


class ServiceProxy:
    """Service proxy for cellaserv."""
    def __init__(self, service_name, client):
        self._service_name = service_name
        self._client = client
        self._identification = None

    def __getattr__(self, action):
        action = ActionProxy(action, self._service_name, self._identification,
                             self._client)
        return action

    def __getitem__(self, identification):
        self._identification = identification
        return self


class CellaservProxy:
    """Proxy class for cellaserv."""
    def __init__(self, client=None):
        if client:
            self._client = client
        else:
            self._client = Client()

    def __getattr__(self, service_name):
        return ServiceProxy(service_name, self._client)

    async def connect(self):
        await self._client.connect()
        asyncio.ensure_future(self._client.loop())

    def __call__(self, event, **kwargs):
        """Send a publish message.

        :param event string: The event name.
        :param kwargs dict: Optional data sent with the event.
        """
        try:
            self._client.publish(event=event, **kwargs)
        except:
            traceback.print_exc()
