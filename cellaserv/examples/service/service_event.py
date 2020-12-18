#!/usr/bin/env python
"""Asynchronous event setting.

Set::

    $ cellaservctl publish some_event
    $ cellaservctl publish my_set

Clear::

    # No clearing event have been declared for some_event
    $ cellaservctl publish my_clear

Passing data::

    $ cellaservctl publish my_set foo=bar

Will display::

    Set! self.variable.data = {'foo': 'bar'}
"""

import asyncio

from cellaserv.service import Event, Service


class Foo(Service):

    some_event = Event()  # set event is 'some_event'
    event = Event(set="my_set", clear="my_clear")

    @Service.coro
    async def coro_loop(self):
        while True:
            print("self.some_event = {}".format(self.some_event.is_set()))

            # Check variable state
            if self.event.is_set():
                print("Set! self.event.data = {}".format(self.event.data))
            else:
                print("Unset.")

            await asyncio.sleep(1)

    @Service.coro
    async def coro_loop_wait(self):
        while True:
            await self.event.wait()
            print("Waited!")
            await asyncio.sleep(1)


async def main():
    foo = Foo()
    await foo.done()


if __name__ == "__main__":
    asyncio.run(main())
