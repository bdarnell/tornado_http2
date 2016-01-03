import struct

from tornado import gen
from tornado.iostream import StreamClosedError
from tornado.locks import Condition

from . import constants
from .errors import ConnectionError, StreamError


class Window(object):
    def __init__(self, parent, stream_id, initial_window_size):
        self.parent = parent
        self.stream_id = stream_id
        self.cond = Condition()
        self.closed = False
        self.size = initial_window_size

    def close(self):
        self.closed = True
        self.cond.notify_all()

    def _raise_error(self, code, message):
        if self.parent is None:
            raise ConnectionError(code, message)
        else:
            raise StreamError(self.stream_id, code)

    def adjust(self, amount):
        self.size += amount
        if self.size > constants.MAX_WINDOW_SIZE:
            self._raise_error(constants.ErrorCode.FLOW_CONTROL_ERROR,
                              "flow control window too large")
        self.cond.notify_all()

    def apply_window_update(self, frame):
        try:
            window_update, = struct.unpack('>I', frame.data)
        except struct.error:
            raise ConnectionError(constants.ErrorCode.FRAME_SIZE_ERROR,
                                  "WINDOW_UPDATE incorrect size")
        # strip reserved bit
        window_update = window_update & 0x7fffffff
        if window_update == 0:
            self._raise_error(constants.ErrorCode.PROTOCOL_ERROR,
                              "window update must not be zero")
        self.adjust(window_update)

    @gen.coroutine
    def consume(self, amount):
        while not self.closed and self.size <= 0:
            yield self.cond.wait()
        if self.closed:
            raise StreamClosedError()
        if self.size < amount:
            amount = self.size
        if self.parent is not None:
            amount = yield self.parent.consume(amount)
        self.size -= amount
        raise gen.Return(amount)
