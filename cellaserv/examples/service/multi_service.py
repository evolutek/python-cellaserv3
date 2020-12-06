#!/usr/bin/env python3

import asyncio
from cellaserv.service import Service


class Ax(Service):
    def __init__(self, ident):
        self._angle = 0
        super().__init__(identification=str(ident))

    @Service.action
    async def set_angle(self, angle):
        self._angle = int(angle)


def main():
    Service.loop([Ax(i) for i in range(10)])


if __name__ == "__main__":
    main()
