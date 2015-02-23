import socket

from tornado.iostream import IOStream
from tornado.testing import AsyncTestCase, gen_test

from ..connection import Connection


class ConnectionTest(AsyncTestCase):
    @gen_test
    def test_settings(self):
        client_sock, server_sock = socket.socketpair()
        self.addCleanup(client_sock.close)
        self.addCleanup(server_sock.close)

        client = Connection(IOStream(client_sock), True)
        server = Connection(IOStream(server_sock), False)

        client_fut = client.start()
        server_fut = server.start()

        yield client_fut
        yield server_fut
