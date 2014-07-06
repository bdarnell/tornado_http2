from distutils.core import setup

try:
    import setuptools
    from setuptools import setup
except ImportError:
    setuptools = None
    from distutils.core import setup

version = '0.0.1'

kwargs = {}

if setuptools is not None:
    kwargs['install_requires'] = ['tornado']

setup(
    name='tornado_http2',
    version=version,
    packages=['tornado_http2', 'tornado_http2.test'],
    **kwargs)
