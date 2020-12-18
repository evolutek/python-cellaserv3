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
async def proxy():
    cs = CellaservProxy()
    await cs.ready()
    yield cs
    await cs.close()
