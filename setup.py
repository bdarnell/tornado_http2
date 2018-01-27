import sys

try:
    import setuptools
    from setuptools import setup
except ImportError:
    setuptools = None
    from distutils.core import setup

version = '0.0.1'

kwargs = {}

with open('README.md') as f:
    kwargs['long_description'] = f.read()

if setuptools is not None:
    kwargs['install_requires'] = ['tornado>=4.5']

    if sys.version_info < (3, 4):
        kwargs['install_requires'].append('enum34')

setup(
    name='tornado_http2',
    version=version,
    packages=['tornado_http2', 'tornado_http2.test'],
    package_data={
        'tornado_http2': [
            'hpack_static_table.txt',
            'hpack_huffman_data.txt',
        ],
        'tornado_http2.test': [
            'test.crt',
            'test.key',
        ],
    },
    license="http://www.apache.org/licenses/LICENSE-2.0",
    description="HTTP/2 add-ons for Tornado",
    classifiers=[
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    **kwargs)
