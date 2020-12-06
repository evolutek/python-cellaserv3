import pytest

from cellaserv.examples.service.date_service import Date
from cellaserv.proxy import CellaservProxy


@pytest.fixture
async def date_service():
    date = Date()
    await date.ready()
    yield date
    await date.kill()


@pytest.mark.asyncio
async def test_date(date_service):
    cs = CellaservProxy()
    await cs.ready()
    assert await cs.date.time() > 0
    await cs.close()
