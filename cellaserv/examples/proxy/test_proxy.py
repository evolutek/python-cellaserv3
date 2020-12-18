import asyncio

import pytest


@pytest.mark.asyncio
async def test_publish(proxy):
    proxy("test")
    proxy("test", foo="bar")
    proxy("test", bar={"a": "b"})


@pytest.mark.asyncio
async def test_concurrent_publish(date_service, proxy):
    # Start tasks in parallel
    coros = [proxy.date.time() for i in range(5)]
    # Wait for all of them
    await asyncio.gather(*coros)


@pytest.mark.asyncio
async def test_bad_publish(proxy):
    # Rational for raise: this have no meaning
    with pytest.raises(TypeError):
        proxy()

    # Rational for raise: arg must by passed as kw
    with pytest.raises(TypeError):
        proxy("event", 0)

    # Rational for raise: bytes are not JSON serializable
    with pytest.raises(TypeError):
        proxy("test", baz=b"aa")


@pytest.mark.asyncio
async def test_logging(proxy):
    proxy("foo")
    proxy("event", foo="bar")
