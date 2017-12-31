import functools

from tornado.escape import utf8
from tornado import gen
from tornado.httpserver import HTTPServer, _HTTPRequestContext
from tornado.httputil import HTTPConnection, RequestStartLine, HTTPMessageDelegate
from tornado.ioloop import IOLoop
from tornado.iostream import SSLIOStream, StreamClosedError, UnsatisfiableReadError
from tornado.log import app_log
from tornado.netutil import ssl_options_to_context
from tornado import stack_context

from tornado_http2.connection import Connection, Params, Stream
from tornado_http2 import constants


class Server(HTTPServer):
    def initialize(self, request_callback, ssl_options=None, **kwargs):
        if ssl_options is not None:
            if isinstance(ssl_options, dict):
                if 'certfile' not in ssl_options:
                    raise KeyError('missing key "certfile" in ssl_options')
                ssl_options = ssl_options_to_context(ssl_options)
            ssl_options.set_alpn_protocols([constants.HTTP2_TLS])
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
            proto = stream.socket.selected_alpn_protocol()
            if proto == constants.HTTP2_TLS:
                self._start_http2(stream, address)
                return
        self._start_http1(stream, address)

    def _start_http1(self, stream, address):
        super(Server, self).handle_stream(stream, address)

    def _start_http2(self, stream, address):
        context = _HTTPRequestContext(stream, address, self.protocol)
        conn = Connection(stream, False, params=self.http2_params, context=context)
        self._connections.add(conn)
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
            stream._read_buffer[:0] = header_data
            stream._read_buffer_size += len(header_data)
            if header_data == b'PRI * HTTP/2.0\r\n\r\n':
                self._start_http2(stream, address)
            else:
                super(CleartextHTTP2Server, self)._start_http1(stream, address)
        except (StreamClosedError, UnsatisfiableReadError):
            pass

    def start_request(self, server_conn, request_conn):
        request_conn = _UpgradingConnection(request_conn,
                                            self.http2_params,
                                            self)
        delegate = super(CleartextHTTP2Server, self).start_request(server_conn, request_conn)
        return _UpgradingRequestAdapter(request_conn, delegate)


class _UpgradingConnection(HTTPConnection):
    def __init__(self, conn, http2_params, server):
        self.conn = conn
        self.context = conn.context
        self.http2_params = http2_params
        self.server = server
        self.upgrading = False
        self.written_headers = None
        self.written_chunks = []
        self.write_finished = False
        self.close_callback = None
        self.max_body_size = None
        self.body_timeout = None

        # TODO: remove
        from tornado.util import ObjectDict
        self.stream = ObjectDict(io_loop=IOLoop.current(), close=conn.stream.close)

    def set_close_callback(self, callback):
        if self.upgrading:
            self.close_callback = stack_context.wrap(callback)
        else:
            self.conn.set_close_callback(callback)

    def set_max_body_size(self, max_body_size):
        if self.upgrading:
            self.max_body_size = max_body_size
        else:
            self.conn.set_max_body_size(max_body_size)

    def set_body_timeout(self, body_timeout):
        if self.upgrading:
            self.body_timeout = body_timeout
        else:
            self.conn.set_body_timeout(body_timeout)

    def detach(self):
        return self.conn.detach()

    def write_headers(self, start_line, headers, chunk=None, callback=None):
        if self.upgrading:
            self.written_headers = (start_line, headers, chunk, callback)
        else:
            return self.conn.write_headers(start_line, headers, chunk, callback)

    def write(self, chunk, callback=None):
        if self.upgrading:
            self.written_chunks.append((chunk, callback))
        else:
            return self.conn.write(chunk, callback)

    def finish(self):
        if self.upgrading:
            self.write_finished = True
        else:
            return self.conn.finish()

    @gen.coroutine
    def switch_protocols(self, callback):
        stream = self.conn.detach()
        stream.write(utf8(
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Connection: Upgrade\r\n"
            "Upgrade: %s\r\n"
            "\r\n" % constants.HTTP2_CLEAR))
        h2_conn = Connection(stream, False, params=self.http2_params,
                             context=self.context)
        self.server._connections.add(h2_conn)
        h2_conn.start(self.server)
        self.conn = Stream(h2_conn, 1, None, context=self.context)
        h2_conn.streams[1] = self.conn
        self.conn._request_start_line = RequestStartLine(
            self._request_start_line.method,
            self._request_start_line.path,
            'HTTP/2.0')
        yield h2_conn._initial_settings_written

        if self.written_headers is not None:
            self.conn.write_headers(*self.written_headers)
        for write in self.written_chunks:
            self.conn.write(*write)
        if self.write_finished:
            self.conn.finish()
        if self.max_body_size is not None:
            self.conn.set_max_body_size(self.max_body_size)
        if self.body_timeout is not None:
            self.conn.set_body_timeout(self.body_timeout)
        if self.close_callback is not None:
            self.conn.set_close_callback(self.close_callback)
            self.close_callback = None
        self.upgrading = False

        try:
            callback()
        except Exception:
            app_log.error("Exception in callback", exc_info=True)
            self.conn.reset()


class _UpgradingRequestAdapter(HTTPMessageDelegate):
    def __init__(self, connection, delegate):
        self.connection = connection
        self.delegate = delegate

    def headers_received(self, start_line, headers):
        if 'Upgrade' in headers:
            upgrades = set(i.strip() for i in headers['Upgrade'].split(','))
            if constants.HTTP2_CLEAR in upgrades:
                self.connection.upgrading = True
                start_line = RequestStartLine(
                    start_line.method, start_line.path, 'HTTP/2.0')
        self.connection._request_start_line = start_line
        return self.delegate.headers_received(start_line, headers)

    def data_received(self, chunk):
        return self.delegate.data_received(chunk)

    def finish(self):
        finish = self.delegate.finish
        if self.connection.upgrading:
            self.connection.switch_protocols(finish)
        else:
            finish()

    def on_connection_close(self):
        self.delegate.on_connection_close()
