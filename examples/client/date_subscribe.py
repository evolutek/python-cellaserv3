#!/usr/bin/env python3

import asyncio
import time

from cellaserv.client import Client


class EpochDelta(Client):
    def __init__(self):
        super().__init__()

    async def on_time(self, now):
        print('{:3.3} msec'.format((time.time() - now) * 1000))


async def main():
    client = EpochDelta()
    await client.connect()
    client.subscribe("time", client.on_time)
    await client.handle_messages()


if __name__ == "__main__":
    asyncio.run(main())
