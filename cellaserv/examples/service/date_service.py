#!/usr/bin/env python3

import asyncio
import time

from cellaserv.service import Service


class Date(Service):
    @Service.action
    async def time(self):
        return int(time.time())

    @Service.action("print_time")
    async def print(self):
        print(time.time())

    @Service.event("hello")
    async def say(self, what="world"):
        print("hello", what)

    @Service.coro
    async def timer(self):
        while not self._disconnect:
            self.log(time=time.time())
            await asyncio.sleep(3)


async def main():
    date_service = Date()
    await date_service.done()


if __name__ == "__main__":
    asyncio.run(main())
