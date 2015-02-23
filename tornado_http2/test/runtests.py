import unittest
import tornado.testing

TEST_MODULES = [
    'tornado_http2.test.connection_test',
    'tornado_http2.test.encoding_test',
    'tornado_http2.test.hpack_test',
]

def all():
    return unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)

def main():
    tornado.testing.main()

if __name__ == '__main__':
    main()
