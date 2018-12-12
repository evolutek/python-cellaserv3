#!/usr/bin/env python3
"""
Sample client, synchronous time request to the date service through cellaserv.
"""

import time

from cellaserv.client import SynClient
from cellaserv.settings import get_socket

WORKERS = 50
REQUESTS_BY_WORKER = 1000


def run_client(n):
    with get_socket() as sock:
        client = SynClient(sock)
        for _ in range(n):
            client.request('time', 'date')


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
