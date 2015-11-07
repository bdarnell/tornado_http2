from tornado.testing import AsyncHTTPTestCase

from tornado_http2.server import CleartextHTTP2Server


class AsyncHTTP2TestCase(AsyncHTTPTestCase):
    def get_http_server(self):
        # TODO: call get_app() a second time or use the non-public self._app?
        app = self.get_app()
        return CleartextHTTP2Server(app, **self.get_httpserver_options())

    # We use the default get_http_client, which relies on
    # configuration from runtests.py. (which is why this is in
    # tornado_http2.test.util instead of tornado_http2.testing)
