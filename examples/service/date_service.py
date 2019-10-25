#!/usr/bin/env python3

import asyncio
import time

from cellaserv.service import Service


class Date(Service):
    @Service.action
    async def time(self):
        return {'time': int(time.time())}

    @Service.action("print_time")
    async def print(self):
        print(time.time())

    @Service.event("hello")
    async def say(self, what="world"):
        print("hello", what)

    @Service.coro
    async def loop(self):
        while True:
            self.log(time=time.time())
            await asyncio.sleep(3)


def main():
    date_service = Date()
    date_service.run()


if __name__ == "__main__":
    main()
