import pytest

from cellaserv.examples.service.date_service import Date
from cellaserv.proxy import CellaservProxy


@pytest.fixture
async def date_service():
    date = Date()
    await date.ready()
    yield date
    await date.kill()


@pytest.fixture
async def cs():
    proxy = CellaservProxy()
    await proxy.ready()
    yield proxy
    await proxy.close()
