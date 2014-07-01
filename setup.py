import os
import sys
import io
from setuptools import setup, find_packages

__author__ = 'Igor Nemilentsev'
__email__ = 'trezorg@gmail.com'
__version__ = '0.0.1'


def read(*names, **kwargs):
    return io.open(
        os.path.join(os.path.dirname(__file__), *names),
        encoding=kwargs.get('encoding', 'utf8')
    ).read().strip()


install_requires=read('requirements.txt').split('\n')
if not sys.version_info >= (3,4):
    install_requires.append('asyncio')


setup(
    name="courseradownloader",
    version=__version__,
    author=__author__,
    author_email=__email__,
    description='asyncio downloader for coursera lectures',
    long_description=read('README.md'),
    license='MIT',
    scripts=['courseradownloader/cdownloader.py'],
    url='https://github.com/trezorg/coursera-downloder.git',
    install_requires=install_requires,
    keywords='coursera, asyncio',
    packages=find_packages(exclude='tests'),
    test_suite='unittest2.collector',
    tests_require=['unittest2'],
    include_package_data = True,
)
