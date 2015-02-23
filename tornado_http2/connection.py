import collections
import struct

from tornado import gen
from tornado.ioloop import IOLoop

from . import constants


class Params(object):
    pass


Frame = collections.namedtuple('Frame', ['type', 'flags', 'stream_id', 'data'])


class Connection(object):
    def __init__(self, stream, is_client, params=None, context=None):
        self.stream = stream
        self.is_client = is_client
        if params is None:
            params = Params()
        self.params = params
        self.context = context

    def start(self):
        fut = self._conn_loop()
        IOLoop.current().add_future(fut, lambda f: f.result())
        return fut

    @gen.coroutine
    def _conn_loop(self):
        try:
            if self.is_client:
                self.stream.write(constants.CLIENT_PREFACE)
            else:
                preface = yield self.stream.read_bytes(
                    len(constants.CLIENT_PREFACE))
                if preface != constants.CLIENT_PREFACE:
                    raise Exception("expected client preface, got %s" %
                                    preface)
            self._write_frame(self._settings_frame())
            while True:
                frame = yield self._read_frame()
                if frame.type == constants.FrameType.SETTINGS:
                    self._handle_settings_frame(frame)
                return
        except:
            self.stream.close()
            raise

    def _write_frame(self, frame):
        # The frame header starts with a 24-bit length. Since `struct`
        # doesn't support 24-bit ints, encode as 32 and slice off the first
        # byte.
        header = struct.pack('>iBBi', len(frame.data), frame.type.value,
                             frame.flags, frame.stream_id)
        encoded_frame = header[1:] + frame.data
        return self.stream.write(encoded_frame)

    @gen.coroutine
    def _read_frame(self):
        header_bytes = yield self.stream.read_bytes(9)
        # Re-attach a leading 0 to parse 24-bit length with struct.
        header = struct.unpack('>iBBi', b'\0' + header_bytes)
        data_len, typ, flags, stream_id = header
        typ = constants.FrameType(typ)
        # Strip the reserved bit off of stream_id
        stream_id = stream_id & 0x7fffffff
        data = yield self.stream.read_bytes(data_len)
        raise gen.Return(Frame(typ, flags, stream_id, data))

    def _settings_frame(self):
        # TODO: parameterize?
        if self.is_client:
            payload = struct.pack('>hi', constants.Setting.ENABLE_PUSH.code, 0)
        else:
            payload = b''
        return Frame(constants.FrameType.SETTINGS, 0, 0, payload)

    def _settings_ack_frame(self):
        return Frame(constants.FrameType.SETTINGS, constants.FrameFlag.ACK,
                     0, b'')

    def _handle_settings_frame(self, frame):
        if frame.flags & constants.FrameFlag.ACK:
            return
        else:
            # TODO: respect changed settings.
            self._write_frame(self._settings_ack_frame())
