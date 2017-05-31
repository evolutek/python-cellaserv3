#!/usr/bin/env python3

import time
from sys import *

from multiprocessing import Process

from cellaserv.service import Service

@Service.hook('realdate')
class Date(Service):
    @Service.action
    def fourty_two(self):
        return 84

class RealDate(Service):
    @Service.action
    def fourty_two(self):
        return 42

def real_date_test():
    real_date = RealDate()
    real_date.run()

def date_test():
    time.sleep(2)
    date = Date()
    date.run()

def main():
    processes = [Process(target=target) for target in [real_date_test, date_test]]
    for p in processes:
        p.start()

    time.sleep(42)

    for p in processes:
        p.terminate()

if __name__ == "__main__":
    main()
