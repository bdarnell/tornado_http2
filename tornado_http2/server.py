import functools

from tornado.httpserver import HTTPServer
from tornado.iostream import SSLIOStream
from tornado.netutil import ssl_options_to_context

from tornado_http2.connection import Connection
from tornado_http2 import constants


class Server(HTTPServer):
    def initialize(self, request_callback, ssl_options=None, **kwargs):
        if ssl_options is not None:
            if isinstance(ssl_options, dict):
                if 'certfile' not in ssl_options:
                    raise KeyError('missing key "certfile" in ssl_options')
                ssl_options = ssl_options_to_context(ssl_options)
            ssl_options.set_npn_protocols([constants.HTTP2_TLS])
        super(Server, self).initialize(
            request_callback, ssl_options=ssl_options, **kwargs)

    def handle_stream(self, stream, address):
        if isinstance(stream, SSLIOStream):
            stream.wait_for_handshake(
                functools.partial(self._handle_handshake, stream, address))
        else:
            self._handle_handshake(stream, address)

    def _handle_handshake(self, stream, address):
        if isinstance(stream, SSLIOStream):
            # TODO: alpn when available
            proto = stream.socket.selected_npn_protocol()
            if proto == constants.HTTP2_TLS:
                conn = Connection(stream, False)
                conn.start(self)
                return
        super(Server, self).handle_stream(stream, address)
