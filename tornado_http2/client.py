import socket
import ssl

from tornado.concurrent import Future
from tornado.escape import to_unicode
from tornado import gen
from tornado.httpclient import AsyncHTTPClient, main, HTTPResponse
from tornado.httputil import RequestStartLine, HTTPHeaders
from tornado.ioloop import IOLoop
from tornado.iostream import SSLIOStream
from tornado.netutil import ssl_options_to_context
from tornado.simple_httpclient import SimpleAsyncHTTPClient, _HTTPConnection

from tornado_http2.connection import Connection
from tornado_http2 import constants

try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse

try:
    from io import BytesIO
except ImportError:
    from cStringIO import StringIO as BytesIO


class Client(SimpleAsyncHTTPClient):
    def _connection_class(self):
        return _HTTP2ClientConnection

class _HTTP2ClientConnection(_HTTPConnection):
    def _get_ssl_options(self, scheme):
        options = super(_HTTP2ClientConnection, self)._get_ssl_options(scheme)
        if options is not None:
            if isinstance(options, dict):
                options = ssl_options_to_context(options)
            options.set_npn_protocols([constants.HTTP2_TLS])
        return options

    def _create_connection(self, stream):
        if isinstance(stream, SSLIOStream):
            proto = stream.socket.selected_npn_protocol()
            if proto == constants.HTTP2_TLS:
                conn = Connection(stream, True)
                IOLoop.current().add_future(conn.start(None),
                                            lambda f: f.result())
                h2_stream = conn.create_stream(self)
                return h2_stream
        return super(_HTTP2ClientConnection, self)._create_connection(stream)


if __name__ == '__main__':
    AsyncHTTPClient.configure(Client)
    main()
