#!/usr/bin/env python3

import time
from multiprocessing import Process

from cellaserv.service import Service


class ServiceA(Service):
    pass


@Service.require('servicea')
class ServiceB(Service):
    pass


@Service.require('servicetest', identification='42')
class ServiceC(Service):
    pass


@Service.require('not_a_service')
class ServiceD(Service):
    pass


class ServiceTest(Service):
    pass


def service_a():
    service_a = ServiceA()
    service_a.run()


def service_b():
    service_b = ServiceB()
    service_b.run()


def service_c():
    service_c = ServiceC()
    service_c.run()


def service_d():
    service_d = ServiceD()
    service_d.run()


def service_test():
    test = ServiceTest(identification='12')
    test.run()


def service_test2():
    test = ServiceTest(identification='42')
    test.run()


def test_require():
    processes = [
        Process(target=target) for target in [
            service_a, service_b, service_c, service_d, service_test,
            service_test2
        ]
    ]

    for p in processes:
        p.start()

    time.sleep(2)

    for p in processes:
        p.terminate()


if __name__ == "__main__":
    test_require()
