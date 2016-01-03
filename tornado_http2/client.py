from tornado.httpclient import AsyncHTTPClient, main
from tornado.ioloop import IOLoop
from tornado.iostream import SSLIOStream
from tornado.netutil import ssl_options_to_context
from tornado.simple_httpclient import SimpleAsyncHTTPClient, _HTTPConnection

from tornado_http2.connection import Connection, Params
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

    def _use_http2_cleartext(self):
        return False


class _HTTP2ClientConnection(_HTTPConnection):
    def _get_ssl_options(self, scheme):
        options = super(_HTTP2ClientConnection, self)._get_ssl_options(scheme)
        if options is not None:
            if isinstance(options, dict):
                options = ssl_options_to_context(options)
            options.set_alpn_protocols([constants.HTTP2_TLS])
        return options

    def _create_connection(self, stream):
        can_http2 = False
        if isinstance(stream, SSLIOStream):
            assert stream.socket.cipher() is not None, 'handshake incomplete'
            proto = stream.socket.selected_alpn_protocol()
            if proto == constants.HTTP2_TLS:
                can_http2 = True
        elif self.client._use_http2_cleartext():
            can_http2 = True
        if can_http2:
            conn = Connection(stream, True,
                              Params(decompress=self.request.decompress_response))
            IOLoop.current().add_future(conn.start(None),
                                        lambda f: f.result())
            h2_stream = conn.create_stream(self)
            return h2_stream
        return super(_HTTP2ClientConnection, self)._create_connection(stream)


class ForceHTTP2Client(Client):
    def _use_http2_cleartext(self):
        return True


if __name__ == '__main__':
    AsyncHTTPClient.configure(Client)
    main()
