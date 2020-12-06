"""Python base class for writing clients for cellaserv.

These classes only manipulates protobuf *messages*. If you are looking for a
high level API you should use ``cellaserv.service.Service``.

Sample usage is provided in the ``example/`` folder of the source distribution.
"""

import functools
import asyncio
import json
import logging
import random
import struct
import traceback
from collections import defaultdict

from google.protobuf.text_format import MessageToString

from cellaserv.protobuf.cellaserv_pb2 import (
    Message,
    Register,
    Request,
    Reply,
    Publish,
    Subscribe,
)

from cellaserv.settings import DEBUG, get_connection

logger = logging.getLogger(__name__)
logger.setLevel(
    logging.DEBUG if DEBUG >= 2 else logging.INFO if DEBUG == 1 else logging.WARNING
)

# Exceptions


class ReplyError(Exception):
    """Indicate that the reply contains an error."""

    def __init__(self, rep):
        self.rep = rep

    def __str__(self):
        return MessageToString(self.rep)


class RequestTimeout(ReplyError):
    """Indicate that the request has timed out."""

    pass


class BadArguments(ReplyError):
    """Indicate that the request arguments were invalid."""

    pass


class NoSuchService(Exception):
    """Indicate that the requested service was not found in the client."""

    def __init__(self, service):
        self.service = service

    def __str__(self):
        return "No such service: {0}".format(self.service)


class NoSuchIdentification(Exception):
    """Indicate that the requested service identification was not found in the
    client."""

    def __init__(self, service, identification):
        self.service = service
        self.identification = identification

    def __str__(self):
        return "No such service identification: {0}.{1}".format(
            self.service, self.identification
        )


class NoSuchMethod(Exception):
    """Indicate that the service does not have the requested method."""

    def __init__(self, service, method):
        self.service = service
        self.method = method

    def __str__(self):
        return "No such method: {0}.{1}".format(self.service, self.method)


class Client:
    """Low level cellaserv client. Sends and receives protobuf messages."""

    def __init__(self, conn=None):
        # Nonce used to identify requests
        # TODO: use atomic int
        self._request_seq_id = random.randrange(0, 2 ** 32)

        # These variables are initialized in connect()
        # Pipes to the cellaserv message broker
        self._conn_read = None
        self._conn_write = None

        # The client is connected to cellaserv.
        self._connected = asyncio.Future()
        # Requests made by this client waiting for a response.
        self._requests_in_flight = {}
        # Topic subscribed to by this client.
        self._subscribes = defaultdict(list)
        # Set this future to disconnect the client.
        self._disconnect = asyncio.Future()
        # Signals that the client is fully disconnected.
        self._disconnected = asyncio.Future()

        # Connect to cellaserv
        self._connect_task = asyncio.create_task(self.connect(conn))
        self._handle_messages_task = asyncio.create_task(self.handle_messages())

    async def connect(self, conn=None):
        """Establish a connection to cellaserv.

        Host and port are determined by the cellaserv.settings module, or by
        the ``conn`` parameter, if provided.
        """
        self._conn_read, self._conn_write = conn or await get_connection()
        self._connected.set_result(True)

    async def connected(self):
        await self._connected

    async def disconnect(self):
        self._disconnect.set_result(True)

        if self._conn_write is not None:
            self._conn_write.close()
            await self._conn_write.wait_closed()
        if self._connect_task:
            self._connect_task.cancel()
        if self._handle_messages_task:
            self._handle_messages_task.cancel()

        self._disconnected.set_result(True)

    def disconnected(self):
        return self._disconnected

    async def handle_messages(self):
        await self._connected

        # Read all messages
        async for msg in self._read_messages():
            self._on_msg_received(msg)

    async def _read_messages(self):
        """Read one message. Wire format is 4-byte size, then data."""
        while True:
            read_header_task = asyncio.create_task(self._conn_read.read(4))
            await asyncio.wait(
                {read_header_task, self._disconnect},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self._disconnect.done():
                # Client was disconnected
                read_header_task.cancel()
                return
            header = read_header_task.result()
            if len(header) == 0:
                # Connection closed
                return
            msg_len = struct.unpack("!I", header)[0]
            msg_bytes = await self._conn_read.read(msg_len)
            msg = Message()
            msg.ParseFromString(msg_bytes)
            yield msg

    def _on_msg_received(self, msg):
        """Handle a cellaserv message."""
        logger.debug("Received:\n%s", msg)
        if msg.type == Message.Request:
            payload = Request()
            coro = self.on_request
        elif msg.type == Message.Reply:
            payload = Reply()
            coro = self.on_reply
        elif msg.type == Message.Publish:
            payload = Publish()
            coro = self.on_publish
        else:
            logger.warning("Unknown message type:\n%s", MessageToString(msg))
            return

        # Parse protobuf message
        payload.ParseFromString(msg.content)
        # Schedule handling of message
        asyncio.create_task(coro(payload))

    async def on_request(self, req):
        # To be implemented by the service
        pass

    async def on_reply(self, reply):
        try:
            request, reply_future = self._requests_in_flight.pop(reply.id)
        except KeyError:
            logger.warning("Unknown request ID for reply: \n%s", reply)
            return

        if reply.error.type != Reply.Error.NoError:
            logger.error("[Reply] Received error")
            if reply.error.type == Reply.Error.Timeout:
                reply_future.set_exception(RequestTimeout(reply))
            elif reply.error.type == Reply.Error.NoSuchService:
                reply_future.set_exception(NoSuchService(request.service_name))
            elif reply.error.type == Reply.Error.InvalidIdentification:
                reply_future.set_exception(
                    NoSuchIdentification(
                        request.service_name, request.service_identification
                    )
                )
            elif reply.error.type == Reply.Error.NoSuchMethod:
                reply_future.set_exception(
                    NoSuchMethod(request.service, request.method)
                )
            elif reply.error.type == Reply.Error.BadArguments:
                reply_future.set_exception(BadArguments(reply))
            else:
                reply_future.set_exception(ReplyError(reply))
            return

        reply_future.set_result(json.loads(reply.data))

    async def send_message(self, msg):
        """Send a cellaserv Message protobuf message."""
        logger.debug("Sending:\n%s", msg)
        msg_data = msg.SerializeToString()
        msg_size_data = struct.pack("!I", len(msg_data))
        await self._connected
        self._conn_write.write(msg_size_data + msg_data)

    async def reply_to(self, req, data=None):
        """
        Send a reply to the request req, with optional data in the reply.

        :param Request req: the original request
        :param bytes data: optional data to put in the reply
        """
        reply = Reply()
        reply.id = req.id
        if data:
            reply.data = data
        msg = Message()
        msg.type = Message.Reply
        msg.content = reply.SerializeToString()
        await self.send_message(msg)

    async def reply_error_to(self, req, error_type, what=None):
        """
        Send an error reply to the request ``req``.

        :param Request req: The original request.
        :param Reply.Error error_type: An error code.
        :param bytes what: an error message.
        """
        error = Reply.Error()
        error.type = error_type
        if what is not None:
            error.what = what

        reply = Reply(id=req.id, error=error)

        msg = Message()
        msg.type = Message.Reply
        msg.content = reply.SerializeToString()
        await self.send_message(msg)

    async def register(self, name, identification=None):
        """
        Send a ``register`` message.

        :param str name: Name of the new service.
        :param str identification: Optional identification for the service.
        """

        register = Register(name=name)
        if identification:
            register.identification = identification

        message = Message(type=Message.Register, content=register.SerializeToString())

        await self.send_message(message)

    async def request(self, method, service, *, identification=None, data=None):
        """
        Send a ``request`` message.

        :param str method: The name of the method.
        :param str service: The name of the service.
        :return: The id of the message that was sent. Used for tracking the
            reply.
        :rtype: int
        """

        logger.info("[Request] %s/%s.%s(%s)", service, identification, method, data)
        request = Request(service_name=service, method=method)
        if identification:
            request.service_identification = identification
        if data:
            request.data = data
        request.id = self._request_seq_id
        self._request_seq_id += 1

        message = Message(type=Message.Request, content=request.SerializeToString())

        # Create a future that will hold the reply in the result
        request_future = asyncio.Future()
        self._requests_in_flight[request.id] = request, request_future
        await self.send_message(message)
        return await request_future

    async def log_exc(self):
        """Log the current exception."""

        str_stack = "".join(traceback.format_exc())
        await self.publish(event="log.error", data=str_stack.encode())

    def publish(self, event, **kwargs):
        """
        Send a ``publish`` message.

        :param event str: The event name.
        :param **kwargs: Optional key=value data sent with the event.
        """

        logger.info("[Publish] %s(%s)", event, kwargs)

        publish = Publish(event=event)
        try:
            data = json.dumps(kwargs)
        except:
            logging.error("Could not serialize publish data: %s", kwargs)
            data = repr(kwargs)
        publish.data = json.dumps(kwargs).encode()

        message = Message(type=Message.Publish, content=publish.SerializeToString())

        asyncio.create_task(self.send_message(message))

    async def on_publish(self, pub):
        logging.info("[Subscribe] Received %s", pub.event)

        # Decode published data
        payload = json.loads(pub.data.decode())
        for cb in self._subscribes[pub.event]:
            logging.debug("[Subscribe] Calling %r(%r)", cb, payload)
            asyncio.create_task(cb(**payload))

    async def subscribe(self, event, cb=None):
        """
        Send a ``subscribe`` message.

        :param str event: The name of the event.
        :param cb func or coro: Callback when the event is received.
        """

        logger.info("[Subscribe] %s", event)

        subscribe = Subscribe(event=event)
        message = Message(type=Message.Subscribe, content=subscribe.SerializeToString())
        if cb is not None:
            self._subscribes[event].append(cb)
        await self.send_message(message)
