import pytest

from cellaserv.service import Service, Variable


class Foo(Service):
    avar = Variable()
    bvar = Variable()
    cvar = Variable("default_value")


@pytest.mark.asyncio
async def test_set_event(cs):
    foo = Foo()
    await foo.ready()

    # Set value
    foo.avar = 42
    assert foo.avar == 42

    # TODO:
    # * test that setting the variable publishes
    # * test that the variable can be set by a publish

    await foo.kill()
