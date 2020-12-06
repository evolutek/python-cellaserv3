import asyncio
import pytest

from cellaserv.examples.fixtures import date_service, proxy
from cellaserv.proxy import CellaservProxy
from cellaserv.service import Service


@pytest.mark.asyncio
async def test_date(date_service, proxy):
    assert await proxy.date.time() > 0


class Ax12(Service):
    def __init__(self, ident):
        super().__init__(identification=str(ident))
        self._angle = 0

    @Service.action
    async def set_angle(self, angle):
        self._angle = int(angle)


@pytest.mark.asyncio
async def test_multiple_services(proxy):
    service_count = 10
    # Create N services
    services = [Ax12(i) for i in range(service_count)]

    # Wait for all services to be ready
    await asyncio.gather(*[service.ready() for service in services])

    # Test requests
    await asyncio.gather(*[proxy.ax12[i].set_angle(i) for i in range(service_count)])

    # Teardown
    await asyncio.gather(*[service.kill() for service in services])
