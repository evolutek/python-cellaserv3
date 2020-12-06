import pytest

from cellaserv.proxy import CellaservProxy


@pytest.mark.asyncio
async def test_publish():
    cs = CellaservProxy()
    await cs.ready()

    cs("test")
    cs("test", foo="bar")
    cs("test", bar={"a": "b"})

    await cs.close()


@pytest.mark.asyncio
async def test_bad_publish():
    cs = CellaservProxy()
    await cs.ready()

    # Rational for raise: this have no meaning
    with pytest.raises(TypeError):
        cs()

    # Rational for raise: arg must by passed as kw
    with pytest.raises(TypeError):
        cs("event", 0)

    # Rational for raise: bytes are not JSON serializable
    with pytest.raises(TypeError):
        cs("test", baz=b"aa")

    await cs.close()
