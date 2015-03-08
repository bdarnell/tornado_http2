import logging
import os
import ssl

from tornado.ioloop import IOLoop
from tornado.options import parse_command_line
from tornado.web import Application, RequestHandler

from tornado_http2.server import Server


class MainHandler(RequestHandler):
    def get(self):
        self.write("Hello world")


def main():
    parse_command_line()
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    ssl_ctx.load_cert_chain(
        os.path.join(os.path.dirname(__file__), 'test.crt'),
        os.path.join(os.path.dirname(__file__), 'test.key'))
    app = Application([('/', MainHandler)], debug=True)
    server = Server(app, ssl_options=ssl_ctx)
    server.listen(8443)
    logging.info("starting")
    IOLoop.instance().start()

if __name__ == '__main__':
    main()
