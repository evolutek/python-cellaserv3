#!/usr/bin/env python3
import asyncio
import configparser
import logging
import os

logging.basicConfig()

config = configparser.ConfigParser()
config.read(['/etc/conf.d/cellaserv'])


def make_setting(name, default, cfg_section, cfg_option, env, coerc=str):
    val = default
    try:
        val = config.get(cfg_section, cfg_option)
    except:
        pass
    val = coerc(os.environ.get(env, val))
    # Inject in the current global namespace
    globals()[name] = val


def make_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if DEBUG >= 1 else logging.INFO)
    return logger


make_setting('HOST', 'localhost', 'client', 'host', 'CS_HOST')
make_setting('PORT', 4200, 'client', 'port', 'CS_PORT', int)
make_setting('DEBUG', 0, 'client', 'debug', 'CS_DEBUG', int)


async def get_connection(loop):
    """Open a socket to cellaserv using user configuration."""
    while True:
        try:
            return await asyncio.open_connection(HOST, PORT, loop=loop)
        except OSError:
            logger.warn("Could not connect to cellaserv: %s:%s", HOST, PORT)
            await asyncio.sleep(1)


logger = make_logger(__name__)
logger.debug("DEBUG: %s", DEBUG)
logger.debug("HOST: %s", HOST)
logger.debug("PORT: %s", PORT)
