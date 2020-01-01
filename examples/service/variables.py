import asyncio

from cellaserv.service import Service, Variable


class Foo(Service):
    avar = Variable()
    bvar = Variable()
    cvar = Variable("default_value")

    def __init__(self):
        super().__init__()

    @Service.coro
    async def test(self):
        while True:
            # Update variable value
            self.avar = "42"
            print(self.cvar)
            await asyncio.sleep(1)


def main():
    foo = Foo()
    foo.run()


if __name__ == "__main__":
    main()
