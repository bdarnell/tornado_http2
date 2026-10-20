import os.path
import ssl

from tornado import gen
from tornado.httpclient import AsyncHTTPClient
from tornado.web import RequestHandler, Application

from tornado_http2.test.util import AsyncHTTP2TestCase


class HelloHandler(RequestHandler):
    def get(self):
        self.write('Hello %s' % self.request.version)


class ServerTest(AsyncHTTP2TestCase):
    def get_app(self):
        class LargeResponseHandler(RequestHandler):
            @gen.coroutine
            def get(self):
                for i in range(200):
                    self.write(b'a' * 1024)
                    yield self.flush()

        return Application([
            ('/hello', HelloHandler),
            ('/large', LargeResponseHandler),
        ])

    def test_hello(self):
        resp = self.fetch('/hello')
        resp.rethrow()
        self.assertEqual(resp.body, b'Hello HTTP/2.0')

    def test_large_response(self):
        # This mainly tests that WINDOW_UPDATE frames are sent as needed,
        # since this response exceeds the default 64KB window.
        resp = self.fetch('/large')
        resp.rethrow()
        self.assertEqual(len(resp.body), 200 * 1024)


class HTTPSTest(AsyncHTTP2TestCase):
    def get_app(self):
        return Application([
            ('/hello', HelloHandler),
        ])

    def get_http_client(self):
        return AsyncHTTPClient(force_instance=True,
                               defaults=dict(validate_cert=False))

    def get_protocol(self):
        return 'https'

    def get_httpserver_options(self):
        module_dir = os.path.dirname(__file__)
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(os.path.join(module_dir, 'test.crt'),
                                os.path.join(module_dir, 'test.key'))
        return dict(ssl_options=ssl_ctx)

    def test_hello(self):
        resp = self.fetch('/hello')
        resp.rethrow()
        self.assertEqual(resp.body, b'Hello HTTP/2.0')
