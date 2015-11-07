from tornado.web import RequestHandler, Application

from tornado_http2.test.util import AsyncHTTP2TestCase


class ServerTest(AsyncHTTP2TestCase):
    def get_app(self):
        class HelloHandler(RequestHandler):
            def get(self):
                self.write('hello')

        return Application([('/hello', HelloHandler)])

    def test_hello(self):
        resp = self.fetch('/hello')
        resp.rethrow()
        self.assertEqual(resp.body, b'hello')
