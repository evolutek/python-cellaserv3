import pytest

from cellaserv.service import Service, Variable


class Foo(Service):
    avar = Variable()
    bvar = Variable()
    cvar = Variable(default={"default": "value"})
    nvar = Variable(name="other_name")
    # TODO: test coerc

    on_update_var = Variable()

    @on_update_var.on_update
    def on_update_cb(self, new_value):
        self.on_updated_cb_called = True


@pytest.mark.asyncio
async def test_set_variables():
    foo = Foo()
    await foo.ready()

    # Set value
    foo.avar = 42
    assert foo.avar == 42

    foo.on_update_var.set("foobar")
    assert foo.on_updated_cb_called

    # TODO:
    # * test that setting the variable publishes
    # * test that the variable can be set by a publish
    # * test other name

    await foo.kill()


@pytest.mark.asyncio
async def test_get_variables(cs):
    foo = Foo()
    await foo.ready()

    assert await cs.foo.get_variables() == [
        {"name": "foo.avar", "value": ""},
        {"name": "foo.bvar", "value": ""},
        {"name": "foo.cvar", "value": {"default": "value"}},
        {"name": "other_name", "value": ""},
        {"name": "foo.on_update_var", "value": ""},
    ]

    await foo.kill()
