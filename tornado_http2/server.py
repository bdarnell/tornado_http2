import logging
import ssl

from tornado import gen
from tornado.httpserver import _ServerRequestAdapter
from tornado.tcpserver import TCPServer

from tornado_http2.connection import Connection
from tornado_http2 import constants


class Server(TCPServer):
    def __init__(self, request_callback, ssl_options=None):
        if ssl_options is None:
            ssl_options = ssl.create_default_context()
        ssl_options.set_npn_protocols(['h2-14', 'h2'])
        super(Server, self).__init__(ssl_options=ssl_options)
        self.request_callback = request_callback

        self.xheaders = False

    @gen.coroutine
    def handle_stream(self, stream, address):
        logging.info('handling stream %r %r', stream, address)
        yield stream.wait_for_handshake()
        # TODO: alpn when available
        proto = stream.socket.selected_npn_protocol()
        if proto == constants.HTTP2_TLS:
            conn = Connection(stream, False)
            conn.start(self)
        else:
            raise Exception("fallback to http1: %s" % proto)

    def start_request(self, server_conn, request_conn):
        return _ServerRequestAdapter(self, server_conn, request_conn)
