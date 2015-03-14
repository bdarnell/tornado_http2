import functools

from tornado import gen
from tornado.httpserver import HTTPServer, _HTTPRequestContext
from tornado.ioloop import IOLoop
from tornado.iostream import SSLIOStream, StreamClosedError
from tornado.netutil import ssl_options_to_context

from tornado_http2.connection import Connection, Params
from tornado_http2 import constants


class Server(HTTPServer):
    def initialize(self, request_callback, ssl_options=None, **kwargs):
        if ssl_options is not None:
            if isinstance(ssl_options, dict):
                if 'certfile' not in ssl_options:
                    raise KeyError('missing key "certfile" in ssl_options')
                ssl_options = ssl_options_to_context(ssl_options)
            ssl_options.set_npn_protocols([constants.HTTP2_TLS])
        # TODO: add h2-specific parameters like frame size instead of header size.
        self.http2_params = Params(
            max_header_size=kwargs.get('max_header_size'),
            decompress=kwargs.get('decompress_request', False),
        )
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
        conn = Connection(stream, False, params=self.http2_params, context=context)
        conn.start(self)


class CleartextHTTP2Server(Server):
    def _start_http1(self, stream, address):
        IOLoop.current().spawn_callback(self._read_first_line, stream, address)

    @gen.coroutine
    def _read_first_line(self, stream, address):
        try:
            header_future = stream.read_until_regex(b'\r?\n\r?\n',
                                                    max_bytes=self.conn_params.max_header_size)
            if self.conn_params.header_timeout is None:
                header_data = yield header_future
            else:
                try:
                    header_data = yield gen.with_timeout(
                        stream.io_loop.time() + self.conn_params.header_timeout,
                        header_future,
                        quiet_exceptions=StreamClosedError)
                except gen.TimeoutError:
                    stream.close()
                    return
            # TODO: make this less hacky
            stream._read_buffer.appendleft(header_data)
            stream._read_buffer_size += len(header_data)
            if header_data == b'PRI * HTTP/2.0\r\n\r\n':
                self._start_http2(stream, address)
            else:
                super(CleartextHTTP2Server, self)._start_http1(stream, address)
        except StreamClosedError:
            pass
