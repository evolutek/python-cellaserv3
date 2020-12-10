# python-cellaserv3

Python3 client library for
[cellaserv3](https://github.com/evolutek/cellaserv3).

## Features

See example usage in `cellaserv/examples/`.

## Install

Install `python-cellaserv3`:

    $ git clone --recurse-submodules https://github.com/evolutek/python-cellaserv3.git
    $ python setup.py develop

## Testing

1. Start the cellaserv3 server locally.
2. Run:

    $ pytest

## Codelab

First, follow the install instructions above.

Then, install and run [cellaserv3](https://github.com/evolutek/cellaserv3):

    $ go get github.com/evolutek/cellaserv3/cmd/...
    $ cellaserv --logs-dir="/tmp"

Let's write our first service, `date.py`:

```python
import asyncio
import time

from cellaserv.service import Service


class Date(Service):
    @Service.action
    async def time(self):
        return int(time.time())

async def main():
    date = Date()
    await date.done()


if __name__ == "__main__":
    asyncio.run(main())
```

Let's disect this file, we can skip the imports, there's nothing particular about them.

```python
class Date(Service):
```

To define a new service, create a new class that inherits from the `Service`
class. The name of the service on cellaserv will be the lowercase string of the
class name, so here: `date`.

```python
    @Service.action
    def time(self):
        return int(time.time())
```

Multiple things are important here. First `@Service.action`, this is a python
decorator. This decorator marks the function as exported to cellaserv.

That's all, you can now run this file:

    $ python date.py
    INFO:cellaserv.service:Service running!

You can go on the cellaserv status page (http://localhost:4280) and you should
see the `date` service in the **Services** column.

We can now query the `time()` action using `cellaservctl`:

    $ cellaservctl request date.time
    DEBU[2020-12-08T18:59:15+01:00] Sending request date[].time({})               module=client
    1607450355

### CellaservProxy

Example:

```
import asyncio

from cellaserv.proxy import CellaservProxy

async def main():
    cs = CellaservProxy()

    # Call the "time" method of the "date" service
    current_time = await cs.date.time()

    # Sending the "tirette" event. Notice that there is no "await" here because
    # sending is scheduled as a background coroutine
    cs("tirette")

    # Start two actions in parallel and wait for both to be completed
    await asyncio.wait([
      cs.robot.gotoxy(x=42, y=1337),
      cs.robot.setup_launcher(),
    ])

    # Start an action...
    task = cs.robot.gotoxy(x=1, y=2)
    # ... meanwhile, do something else ...
    await cs.robot.blink()
    # ... finally wait for the first task to finish
    await task

    # Start an action with a timeout
    try:
	await asyncio.wait_for(cs.robot.gotothetha(90), timeout=1)
    except asyncio.TimeoutError:
	print("Ooops")

if __name__ == "__main__":
    asyncio.run(main())
```

## Authors

- Rémi Audebert, Evolutek 2012-2020
- Benoît Reitz, Evolutek 2013-2015
- Adrien Schildknecht, Evolutek 2013-2015
- Vincent Gatine, Evolutek 2014-2015
- Corentin Vigourt, Evolutek 2014-2020
