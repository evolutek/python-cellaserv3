#!/usr/bin/env python3

import asyncio
import time

from cellaserv.service import Service, ConfigVariable


class Date(Service):

    coef = ConfigVariable("test", "coef")

    def __init__(self):
        super().__init__()
        self._time = time.time()

    @Service.action
    async def time(self):
        return self._time

    @Service.coro
    async def coro1(self):
        print("Coro 1 started")
        while True:
            await asyncio.sleep(1)
            self._time = time.time() * float(self.coef())

    @Service.coro
    async def coro2(self):
        print("Coro 2 started")
        while True:
            await asyncio.sleep(1)
            print(self.coef())


def main():
    date_service = Date()
    date_service.run()


if __name__ == "__main__":
    main()
