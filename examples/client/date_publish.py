#!/usr/bin/env python3
"""Use the cellaserv client to send publish every second."""

import asyncio
import time

from cellaserv.client import Client


class DatePublisher(Client):
    def __init__(self):
        super().__init__()

    def publish_time(self):
        self.publish('time', now=time.time())


async def main():
    date = DatePublisher()
    await date.connect()
    while True:
        await asyncio.sleep(1)
        date.publish_time()


if __name__ == '__main__':
    asyncio.run(main())
