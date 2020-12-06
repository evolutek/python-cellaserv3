#!/usr/bin/env python3

import asyncio
from cellaserv.proxy import CellaservProxy


async def main():
    cs = CellaservProxy()
    await cs.connect()

    # Start tasks in parallel
    coros = [cs.slow.wait(duration=i) for i in range(5)]
    # Wait for all of them
    await asyncio.gather(*coros)

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
