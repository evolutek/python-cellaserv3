# python-cellaserv3

Python3 client library for
[cellaserv3](https://github.com/evolutek/cellaserv3).

## Features

See example usage in `cellaserv/examples/`.

## Install

Install `python-cellaserv3`:

    $ git clone https://github.com/evolutek/python-cellaserv3.git
    $ cd python-cellaserv3
    $ git submodule init
    $ git submodule update cellaserv/protobuf
    $ python setup.py develop

## Testing

1. Start the cellaserv3 server.
2. Run:

    $ pytest

## Authors

- Rémi Audebert, Evolutek 2012-2020
- Benoît Reitz, Evolutek 2013-2015
- Adrien Schildknecht, Evolutek 2013-2015
- Vincent Gatine, Evolutek 2014-2015
- Corentin Vigourt, Evolutek 2014-2020
