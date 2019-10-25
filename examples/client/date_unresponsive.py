#!/usr/bin/env python3
"""
Using the cellaserv module to implement a service that does nothing. Used to
test timeouts.
"""
import asyncio

from cellaserv.client import Client


class DateService(Client):
    def __init__(self):
        super().__init__()

    async def on_request(self, req):
        pass


async def main():
    service = DateService()
    await service.connect()
    await service.register('date')
    await service.loop()


if __name__ == "__main__":
    asyncio.run(main())
