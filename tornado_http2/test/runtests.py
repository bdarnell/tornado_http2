import logging
from tornado.httpclient import AsyncHTTPClient
from tornado.options import define, options, add_parse_callback
import tornado.testing
import unittest

TEST_MODULES = [
    'tornado_http2.test.encoding_test',
    'tornado_http2.test.hpack_test',
    'tornado_http2.test.server_test',
]


def all():
    return unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)


def main():
    define('httpclient', type=str, default=None)

    def configure_httpclient():
        if options.httpclient is not None:
            AsyncHTTPClient.configure(options.httpclient)
        else:
            AsyncHTTPClient.configure('tornado_http2.client.ForceHTTP2Client')
    add_parse_callback(configure_httpclient)

    logging.getLogger("tornado.access").setLevel(logging.CRITICAL)
    tornado.testing.main()

if __name__ == '__main__':
    main()
