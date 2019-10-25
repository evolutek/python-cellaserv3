#!/usr/bin/env python3
"""
Sample date.time request through cellaserv using the Client class.
"""

import asyncio

from cellaserv.client import Client


class TimeRequestClient(Client):
    def __init__(self):
        super().__init__()

    def time(self):
        return self.request('time', 'date')


async def main():
    client = TimeRequestClient()
    await client.connect()
    asyncio.get_event_loop().create_task(client.loop())
    for i in range(10):
        print(await client.time())


if __name__ == "__main__":
    asyncio.run(main())
