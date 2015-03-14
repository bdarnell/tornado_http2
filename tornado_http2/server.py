import functools

from tornado import gen
from tornado.httpserver import HTTPServer, _HTTPRequestContext
from tornado.ioloop import IOLoop
from tornado.iostream import SSLIOStream, StreamClosedError
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

    def _use_http2_cleartext(self):
        return False

    def handle_stream(self, stream, address):
        if isinstance(stream, SSLIOStream):
            stream.wait_for_handshake(
                functools.partial(self._handle_handshake, stream, address))
        else:
            self._handle_handshake(stream, address)

    def _handle_handshake(self, stream, address):
        if isinstance(stream, SSLIOStream):
            assert stream.socket.cipher(), 'handshake incomplete'
            # TODO: alpn when available
            proto = stream.socket.selected_npn_protocol()
            if proto == constants.HTTP2_TLS:
                self._start_http2(stream, address)
                return
        self._start_http1(stream, address)

    def _start_http1(self, stream, address):
        super(Server, self).handle_stream(stream, address)

    def _start_http2(self, stream, address):
        context = _HTTPRequestContext(stream, address, self.protocol)
        conn = Connection(stream, False, context=context)
        conn.start(self)


class CleartextHTTP2Server(Server):
    def _start_http1(self, stream, address):
        IOLoop.current().spawn_callback(self._read_first_line, stream, address)

    @gen.coroutine
    def _read_first_line(self, stream, address):
        try:
            first_line = yield stream.read_until(b'\r\n\r\n')
            # TODO: make this less hacky
            stream._read_buffer.appendleft(first_line)
            stream._read_buffer_size += len(first_line)
            if first_line == b'PRI * HTTP/2.0\r\n\r\n':
                self._start_http2(stream, address)
            else:
                super(CleartextHTTP2Server, self)._start_http1(stream, address)
        except StreamClosedError:
            pass
