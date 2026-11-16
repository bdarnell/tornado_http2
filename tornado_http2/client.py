import functools
import ssl

from tornado.httpclient import AsyncHTTPClient, main
from tornado.ioloop import IOLoop
from tornado.iostream import SSLIOStream
from tornado import netutil
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


def _shared_contexts():
    # Contexts that Tornado caches and shares between requests (and
    # with other clients), so we must not modify them.
    shared = []
    for name in ('_client_ssl_defaults', '_client_ssl_noverify'):
        ctx = getattr(netutil, name, None)
        if callable(ctx):
            # Tornado 6.6+ creates these lazily (and adds
            # _client_ssl_noverify); 6.5 has a module-level context.
            ctx = ctx()
        if ctx is not None:
            shared.append(ctx)
    return shared


@functools.lru_cache(maxsize=8)
def _alpn_context(base):
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = base.check_hostname
    ctx.verify_mode = base.verify_mode
    ctx.options = base.options
    ctx.set_alpn_protocols([constants.HTTP2_TLS])
    return ctx


class _HTTP2ClientConnection(_HTTPConnection):
    def _get_ssl_options(self, scheme):
        options = super(_HTTP2ClientConnection, self)._get_ssl_options(scheme)
        if options is not None:
            if isinstance(options, dict):
                options = ssl_options_to_context(options, server_side=False)
            elif any(options is ctx for ctx in _shared_contexts()):
                # Don't modify Tornado's shared contexts; use an
                # ALPN-enabled copy instead.
                options = _alpn_context(options)
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
            # Connection closes are reported through the HTTP/2 stream.
            stream.set_close_callback(None)
            conn = Connection(stream, True,
                              Params(decompress=self.request.decompress_response,
                                     max_body_size=self.max_body_size))
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
