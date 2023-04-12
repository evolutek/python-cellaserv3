try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name='python-cellaserv3',
    version='1.0',
    url='https://bitbucket.org/evolutek/python-cellaserv3',
    description='Python client for cellaserv3',
    author='Evolutek',
    author_email='evolutek@googlegroups.com',
    install_requires=["protobuf>=3.19"],
    packages=['cellaserv', 'cellaserv.protobuf'],
    tests_require=['pytest', 'pytest-timeout'],
    classifiers=[
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
)
