import time
from tornado import gen
from tornado.httpclient import AsyncHTTPClient
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
from tornado.options import define, options, parse_command_line
from tornado.testing import bind_unused_port
from tornado.web import Application, RequestHandler
import tornado_http2.client
import tornado_http2.server


define('n', default=1000)
define('versions', multiple=True, default=['1', '2'])


class HelloHandler(RequestHandler):
    def get(self):
        self.write("Hello world")


@gen.coroutine
def benchmark(version):
    app = Application([('/', HelloHandler)])
    if version == 1:
        server = HTTPServer(app)
        client = AsyncHTTPClient()
    elif version == 2:
        server = tornado_http2.server.CleartextHTTP2Server(app)
        client = tornado_http2.client.ForceHTTP2Client()

    sock, port = bind_unused_port()
    try:
        server.add_socket(sock)
        url = 'http://localhost:%d/' % port

        start = time.time()
        for i in range(options.n):
            yield client.fetch(url)
        end = time.time()
        return end - start
    finally:
        server.stop()
        sock.close()


def print_result(label, elapsed):
    print('HTTP/%s: %d requests in %0.3fs: %f QPS' % (label, options.n, elapsed,
          options.n / elapsed))


@gen.coroutine
def main():
    options.logging = "warning"
    parse_command_line()

    for version in options.versions:
        elapsed = yield benchmark(int(version))
        print_result(version, elapsed)

if __name__ == '__main__':
    IOLoop.current().run_sync(main)
