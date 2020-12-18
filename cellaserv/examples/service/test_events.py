import pytest

from cellaserv.examples.fixtures import proxy
from cellaserv.service import Event, Service


class Foo(Service):
    a = Event()
    b = Event()


@pytest.mark.asyncio
async def test_set_event(proxy):
    foo = Foo()
    await foo.ready()

    assert not foo.a.is_set()
    proxy("a")  # set event
    await foo.a.wait()

    assert foo.a.is_set()

    proxy("b", foo=42)  # set event with data
    await foo.b.wait()

    assert foo.b.is_set()
    assert foo.b.data() == {"foo": 42}

    await foo.kill()


@pytest.mark.asyncio
async def test_set_unset_event(proxy):
    foo = Foo()
    await foo.ready()

    proxy("a")  # set event
    await foo.a.wait()

    proxy("a_clear")  # set event
    await foo.a.wait_reset()

    await foo.kill()
