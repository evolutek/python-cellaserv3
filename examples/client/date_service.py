#!/usr/bin/env python3
"""
Using the cellaserv Client class to implement a service answering to the "time"
command.
"""

import asyncio
import time

from cellaserv.client import Client
from cellaserv.protobuf.cellaserv_pb2 import Reply


class DateService(Client):
    def __init__(self):
        super().__init__()

    async def on_request(self, req):
        if req.method == 'time':
            self.reply_to(req, str(time.time()).encode())
        else:
            self.reply_error_to(req, Reply.Error.NoSuchMethod)


async def main():
    client = DateService()
    await client.connect()
    await client.register("date")
    await client.handle_messages()


if __name__ == "__main__":
    asyncio.run(main())
