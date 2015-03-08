import socket
import ssl

from tornado.concurrent import Future
from tornado.escape import to_unicode
from tornado import gen
from tornado.httpclient import AsyncHTTPClient, main, HTTPResponse
from tornado.httputil import RequestStartLine, HTTPHeaders
from tornado.ioloop import IOLoop
from tornado.iostream import SSLIOStream

from tornado_http2.connection import Connection

try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse

try:
    from io import BytesIO
except ImportError:
    from cStringIO import StringIO as BytesIO


class Client(AsyncHTTPClient):
    def fetch_impl(self, request, callback):
        IOLoop.current().add_future(self._real_fetch(request),
                                    lambda f: callback(f.result()))

    @gen.coroutine
    def _real_fetch(self, request):
        parsed = urlparse.urlsplit(to_unicode(request.url))
        if parsed.scheme != 'https':
            raise Exception('only https')
        port = parsed.port or 443
        ctx = ssl.create_default_context()
        ctx.set_npn_protocols(['h2-14'])
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        stream = SSLIOStream(socket.socket(), ssl_options=ctx)
        yield stream.connect((parsed.hostname, port),
                             server_hostname=parsed.hostname)
        if stream.socket.selected_npn_protocol() != 'h2-14':
            raise Exception('only http2')
        conn = Connection(stream, True)
        IOLoop.current().add_future(conn.start(None), lambda f: f.result())
        h2_stream = conn.create_stream(self)
        self.finish_future = Future()
        self.body = BytesIO()
        h2_stream.write_headers(RequestStartLine(request.method,
                                                 parsed.path or b'/',
                                                 'HTTP/2.0'),
                                HTTPHeaders())
        h2_stream.finish()
        yield self.finish_future
        response = HTTPResponse(request, self.start_line.code,
                                headers=self.headers,
                                buffer=self.body)
        stream.close()
        raise gen.Return(response)

    def headers_received(self, start_line, headers):
        self.start_line = start_line
        self.headers = headers

    def data_received(self, chunk):
        self.body.write(chunk)

    def finish(self):
        self.finish_future.set_result(None)

if __name__ == '__main__':
    AsyncHTTPClient.configure(Client)
    main()
