import pytest

from cellaserv.service import Event, Service


class Foo(Service):
    a = Event()
    b = Event()


@pytest.mark.asyncio
async def test_set_event(cs):
    foo = Foo()
    await foo.ready()

    assert not foo.a.is_set()
    cs("a")  # set event
    await foo.a.wait_set()

    assert foo.a.is_set()

    cs("b", foo=42)  # set event with data
    await foo.b.wait_set()

    assert foo.b.is_set()
    assert foo.b.data() == {"foo": 42}

    await foo.kill()


@pytest.mark.asyncio
async def test_set_unset_event(cs):
    foo = Foo()
    await foo.ready()

    cs("a")  # set event
    await foo.a.wait_set()

    cs("a_clear")  # set event
    await foo.a.wait_clear()

    await foo.kill()
