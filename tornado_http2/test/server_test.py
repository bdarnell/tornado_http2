from tornado import gen
from tornado.web import RequestHandler, Application

from tornado_http2.test.util import AsyncHTTP2TestCase


class ServerTest(AsyncHTTP2TestCase):
    def get_app(self):
        class HelloHandler(RequestHandler):
            def get(self):
                self.write('hello')

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
        self.assertEqual(resp.body, b'hello')

    def test_large_response(self):
        # This mainly tests that WINDOW_UPDATE frames are sent as needed,
        # since this response exceeds the default 64KB window.
        resp = self.fetch('/large')
        resp.rethrow()
        self.assertEqual(len(resp.body), 200 * 1024)
