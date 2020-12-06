import pytest

from cellaserv.examples.fixtures import date_service, proxy
from cellaserv.proxy import CellaservProxy


@pytest.mark.asyncio
async def test_date(date_service, proxy):
    assert await proxy.date.time() > 0
