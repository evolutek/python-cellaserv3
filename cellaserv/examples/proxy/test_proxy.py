import asyncio

import pytest


@pytest.mark.asyncio
async def test_publish(cs):
    cs("test")
    cs("test", foo="bar")
    cs("test", bar={"a": "b"})


@pytest.mark.asyncio
async def test_concurrent_publish(date_service, cs):
    # Start tasks in parallel
    coros = [cs.date.time() for i in range(5)]
    # Wait for all of them
    await asyncio.gather(*coros)


@pytest.mark.asyncio
async def test_bad_publish(cs):
    # Rational for raise: this have no meaning
    with pytest.raises(TypeError):
        cs()

    # Rational for raise: arg must by passed as kw
    with pytest.raises(TypeError):
        cs("event", 0)

    # Rational for raise: bytes are not JSON serializable
    with pytest.raises(TypeError):
        cs("test", baz=b"aa")


@pytest.mark.asyncio
async def test_logging(cs):
    cs("foo")
    cs("event", foo="bar")
