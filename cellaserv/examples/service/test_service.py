import asyncio

import pytest

from cellaserv.service import Service


class Basic(Service):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.a_future = asyncio.Future()

    @Service.action
    def return_0(self):
        return 0

    @Service.action
    def simple_function(self):
        return True

    @Service.action
    async def async_function(self):
        return True

    @Service.action
    async def wait_future(self):
        await self.a_future
        return True

    @Service.action
    def set_future(self):
        self.a_future.set_result(True)


@pytest.mark.asyncio
async def test_basic_service(cs):
    basic = Basic()
    await basic.ready()

    assert await cs.basic.return_0() == 0

    assert await cs.basic.simple_function()

    assert await cs.basic.async_function()

    assert await asyncio.gather(cs.basic.wait_future(), cs.basic.set_future())

    await basic.kill()


@pytest.mark.asyncio
async def test_date(date_service, cs):
    assert await cs.date.time() > 0


class Ax12(Service):
    def __init__(self, ident):
        super().__init__(identification=str(ident))
        self._angle = 0

    @Service.action
    async def set_angle(self, angle):
        self._angle = int(angle)


@pytest.mark.asyncio
async def test_multiple_services(cs):
    service_count = 10
    # Create N services
    services = [Ax12(i) for i in range(service_count)]

    # Wait for all services to be ready
    await asyncio.gather(*[service.ready() for service in services])

    # Test requests
    await asyncio.gather(*[cs.ax12[i].set_angle(i) for i in range(service_count)])

    # Teardown
    await asyncio.gather(*[service.kill() for service in services])


class LogService(Service):
    def send_logs(self):
        self.log("1")
        self.log({"test": 42})
        self.log(foo="bar")

    @Service.action
    def do_log(self):
        self.send_logs()

    @Service.action
    async def async_do_log(self):
        self.send_logs()


@pytest.mark.asyncio
async def test_log(cs):
    s = LogService()
    await s.ready()

    await cs.logservice.do_log()
    await cs.logservice.async_do_log()

    await s.kill()
