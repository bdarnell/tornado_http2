try:
    import setuptools
    from setuptools import setup
except ImportError:
    setuptools = None
    from distutils.core import setup

version = '0.0.1'

kwargs = {}

if setuptools is not None:
    kwargs['install_requires'] = ['tornado>=6.5.6']
    kwargs['python_requires'] = '>=3.10'

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
    **kwargs)
