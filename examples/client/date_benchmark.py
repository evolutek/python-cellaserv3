#!/usr/bin/env python3
"""
Sample client, synchronous time request to the date service through cellaserv.
"""

import asyncio
import time

from cellaserv.client import Client

WORKERS = 50
REQUESTS_BY_WORKER = 1000


async def tb(n):
    client = Client()
    await client.connect()
    asyncio.create_task(client.loop())
    reps = []
    for _ in range(n):
        reps.append(client.request('time', 'date'))
    await asyncio.gather(*reps)


def run_client(n):
    asyncio.run(tb(n))


def main():
    from multiprocessing import Pool
    print("Starting {} workers doing {} requests".format(
        WORKERS, REQUESTS_BY_WORKER))
    p = Pool(WORKERS)
    begin = time.perf_counter()
    p.map(run_client, [REQUESTS_BY_WORKER] * WORKERS)
    end = time.perf_counter()
    print((end - begin) * 1000)


if __name__ == "__main__":
    main()
