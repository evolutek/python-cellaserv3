import asyncio
import time

import pytest

from cellaserv.service import ConfigVariable, Service


class CoroService(Service):
    def __init__(self):
        super().__init__()

        self._coro1_started = asyncio.Future()
        self._coro2_started = asyncio.Future()

    @Service.coro
    async def coro1(self):
        self._coro1_started.set_result(True)
        await self._coro2_started

    @Service.coro
    async def coro2(self):
        await self._coro1_started
        self._coro2_started.set_result(True)


@pytest.mark.asyncio
async def test_coros():
    service = CoroService()
    await service.ready()

    await asyncio.gather(*[service._coro1_started, service._coro2_started])

    await service.kill()
