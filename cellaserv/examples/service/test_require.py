#!/usr/bin/env python3
import pytest

from cellaserv.service import Service


class ServiceA(Service):
    pass


@Service.require("servicea")
class ServiceDependsOnA(Service):
    pass


@Service.require("servicetest", identification="42")
class ServiceC(Service):
    pass


@Service.require("not_a_service")
class ServiceD(Service):
    pass


class ServiceTest(Service):
    pass


@pytest.mark.asyncio
async def test_require_in_order():
    a = ServiceA()
    b = ServiceDependsOnA()
    await a.ready()
    await b.ready()

    # TODO assert

    await a.kill()
    await b.kill()
    await a.done()
    await b.done()


@pytest.mark.asyncio
async def test_require_out_of_order():
    a = ServiceDependsOnA()
    b = ServiceA()
    await a.ready()
    await b.ready()

    # TODO assert

    await a.kill()
    await b.kill()
    await a.done()
    await b.done()
