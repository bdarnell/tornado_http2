import os
from unittest import skipIf
from tornado.options import define, options
from tornado.process import Subprocess
from tornado.testing import AsyncHTTPSTestCase, gen_test
from tornado.web import Application, RequestHandler

from tornado_http2.server import Server

define("h2spec_section", type=str, multiple=True,
       help="h2spec section to run (e.g. 'http2/6.2')")


# h2spec binaries can be downloaded from
# https://github.com/summerwind/h2spec/releases (tested with v2.6.0).
@skipIf("H2SPEC" not in os.environ,
        "H2SpecTest only run when H2SPEC is set to the path of h2spec")
class H2SpecTest(AsyncHTTPSTestCase):
    # h2spec talks to the server over TLS (negotiating HTTP/2 with ALPN)
    # because some of its tests can't pass on a cleartext server that also
    # accepts HTTP/1: an invalid connection preface gets an HTTP/1 response.
    def get_http_server(self):
        return Server(self._app, ssl_options=self.get_ssl_options())

    def get_app(self):
        # h2spec cares very little about the server it's talking to:
        # It is just concerned with the low-level framing so a server that
        # returns nothing but 404s is fine. However, its flow control
        # test is only executed if a request for / has a non-empty body.
        class HelloHandler(RequestHandler):
            def get(self):
                self.write("Hello, world")

            def post(self):
                self.write("Hello, world")
        return Application([('/', HelloHandler)])

    # This encapsulates a lot of tests, and when things are failing
    # it can take a while to run, so give it a longer timeout.
    @gen_test(timeout=300)
    def test_h2spec(self):
        h2spec_cmd = [os.environ["H2SPEC"], "-p", str(self.get_http_port()),
                      "--tls", "--insecure"]
        h2spec_cmd.extend(options.h2spec_section)
        h2spec_proc = Subprocess(h2spec_cmd)
        yield h2spec_proc.wait_for_exit()
