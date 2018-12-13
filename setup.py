try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name='python-cellaserv3',
    version='git',
    url='https://bitbucket.org/evolutek/python-cellaserv3',
    description='Python client for cellaserv3',
    author='Evolutek - 2018',
    author_email='evolutek@googlegroups.com',
    install_requires=open('requirements.txt').read().splitlines(),
    packages=['cellaserv', 'cellaserv.protobuf'],
    test_requires=['pytest', 'pytest-timeout'],
    classifiers=[
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
)
