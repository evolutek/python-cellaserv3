#!/usr/bin/env python3

from multiprocessing import Process
from time import sleep

from cellaserv.proxy import CellaservProxy
from cellaserv.service import Service


class ServiceTest(Service):
    @Service.action
    def foo(self):
        return "bar"

    @Service.action
    def echo(self, str):
        return str


def setup_function(f):
    f.p = Process(target=main)
    f.p.start()
    sleep(.2)


def teardown_function(f):
    f.p.terminate()


def test_basic():
    cs = CellaservProxy()

    srvcs = cs.cellaserv.list_services()

    # Check for presence
    foo = False
    bar = False
    for srvc in srvcs:
        if srvc["name"] == "servicetest":
            if srvc["identification"] == "foo":
                assert not foo
                foo = True
            if srvc["identification"] == "bar":
                assert not bar
                bar = True
    assert foo
    assert bar

    assert cs.servicetest["foo"].foo() == "bar"
    assert cs.servicetest["bar"].foo() == "bar"
    assert cs.servicetest["foo"].echo("a") == "a"
    assert cs.servicetest["bar"].echo("b") == "b"


def main():
    tf = ServiceTest("foo")
    tb = ServiceTest("bar")

    Service.loop()


if __name__ == '__main__':
    main()
