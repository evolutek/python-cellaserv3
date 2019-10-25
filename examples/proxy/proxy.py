#!/usr/bin/env python3
"""How to use cellaserv.proxy.CellaservProxy"""

import asyncio
from cellaserv.proxy import CellaservProxy


async def main():
    cs = CellaservProxy()
    await cs.connect()

    print(await cs.date.time())
    cs("hello")
    cs("hello", what="you")
    cs("kill")


if __name__ == "__main__":
    asyncio.run(main())
