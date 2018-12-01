import multiprocessing
import time

from cellaserv.service import Service
from cellaserv.proxy import CellaservProxy


class ServiceTest(Service):
    @Service.action
    def args(self, *args):
        return args

    @Service.action
    def kw(self, a, b):
        return [a, b]


def test_args():
    # Start our test service
    p = multiprocessing.Process(target=main)
    p.start()
    time.sleep(.2)  # Give it time to start

    cs = CellaservProxy()

    assert cs.servicetest.args(1, 2, 3) == [1, 2, 3]
    assert cs.servicetest.kw(1, 2) == [1, 2]
    assert cs.servicetest.kw(a=1, b=2) == [1, 2]
    assert cs.servicetest.kw(1, b=2) is None

    p.terminate()


def main():
    t = ServiceTest()
    t.run()


if __name__ == '__main__':
    main()
