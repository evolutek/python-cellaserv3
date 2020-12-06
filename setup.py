try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name="python-cellaserv3",
    version="git",
    url="https://github.com/evolutek/python-cellaserv3",
    description="Python client for cellaserv3",
    author="Evolutek",
    author_email="evolutek@googlegroups.com",
    install_requires=open("requirements.txt").read().splitlines(),
    packages=["cellaserv", "cellaserv.protobuf"],
    tests_require=["pytest", "pytest-asyncio"],
    classifiers=[
        "Programming Language :: Python :: 3.8",
    ],
)
