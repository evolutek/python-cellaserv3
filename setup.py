import setuptools

setuptools.setup(
    name="python-cellaserv3",
    version="git",
    url="https://github.com/evolutek/python-cellaserv3",
    description="Python client for cellaserv3",
    author="Evolutek",
    author_email="evolutek@googlegroups.com",
    install_requires=open("requirements.txt").read().splitlines(),
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3.8",
    ],
    python_requires=">=3.8",
)
