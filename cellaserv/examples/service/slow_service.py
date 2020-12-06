#!/usr/bin/env python3

import asyncio

from cellaserv.service import Service


class Slow(Service):
    @Service.action
    async def wait(self, duration):
        print(f"Sleeping {duration} seconds")
        await asyncio.sleep(int(duration))
        print(f"Done!")
        return duration


def main():
    slow_service = Slow()
    slow_service.run()


if __name__ == "__main__":
    main()
