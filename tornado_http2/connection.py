import logging
import struct

from tornado.concurrent import Future
from tornado.escape import utf8
from tornado import gen
from tornado.httputil import HTTPOutputError
from tornado.ioloop import IOLoop
from tornado.iostream import StreamClosedError
from tornado.log import gen_log

from . import constants
from .errors import ConnectionError, StreamError
from .frames import Frame, parse_window_update_frame
from .hpack import HpackDecoder, HpackEncoder
from .stream import Stream


class Params(object):
    def __init__(self, chunk_size=None, max_header_size=None, decompress=False):
        self.chunk_size = chunk_size or 65536
        self.max_header_size = max_header_size or 65536
        self.decompress = decompress


class Connection(object):
    def __init__(self, stream, is_client, params=None, context=None):
        self.stream = stream
        self.is_client = is_client
        if params is None:
            params = Params()
        self.params = params
        self.context = context
        self._initial_settings_written = Future()
        self._serving_future = None

        self.streams = {}
        self.next_stream_id = 1 if is_client else 2
        self.hpack_decoder = HpackDecoder(
            constants.Setting.HEADER_TABLE_SIZE.default)
        self.hpack_encoder = HpackEncoder(
            constants.Setting.HEADER_TABLE_SIZE.default)
        self.flow_window = constants.Setting.INITIAL_WINDOW_SIZE.default

    @gen.coroutine
    def close(self):
        self.stream.close()
        # Block until the serving loop is done, but ignore any exceptions
        # (start() is already responsible for logging them).
        try:
            yield self._serving_future
        except Exception:
            pass

    def start(self, delegate):
        self._serving_future = self._conn_loop(delegate)
        IOLoop.current().add_future(self._serving_future, lambda f: f.result())
        return self._serving_future

    def create_stream(self, delegate):
        stream = Stream(self, self.next_stream_id, delegate,
                        context=self.context)
        self.next_stream_id += 2
        self.streams[stream.stream_id] = stream
        return stream

    @gen.coroutine
    def _conn_loop(self, delegate):
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
            self._initial_settings_written.set_result(None)
            max_remote_stream_id = 0
            last_stream = None
            while True:
                try:
                    frame = yield self._read_frame()
                    logging.debug('got frame %r', frame)
                    if last_stream is not None and last_stream.needs_continuation():
                        if (frame.type != constants.FrameType.CONTINUATION or
                                frame.stream_id != last_stream.stream_id):
                            raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                                  "CONTINUATION frame required")
                    if frame.stream_id == 0:
                        self.handle_frame(frame)
                    elif frame.stream_id in self.streams:
                        last_stream = self.streams[frame.stream_id]
                        last_stream.handle_frame(frame)
                    elif (not self.is_client and
                          frame.type == constants.FrameType.HEADERS):
                        if (frame.stream_id & 1) == (self.next_stream_id & 1):
                            # The remote is trying to use our local keyspace
                            raise ConnectionError(
                                constants.ErrorCode.PROTOCOL_ERROR,
                                "invalid stream id")
                        if frame.stream_id > max_remote_stream_id:
                            max_remote_stream_id = frame.stream_id
                        stream = Stream(self, frame.stream_id, None,
                                        context=self.context)
                        stream.set_delegate(delegate.start_request(self, stream))
                        self.streams[frame.stream_id] = stream
                        last_stream = stream
                        stream.handle_frame(frame)
                    else:
                        # We don't have the stream and can't create it.
                        # The error depends on whether the stream id
                        # is from the past or future.
                        is_local = ((frame.stream_id & 1) ==
                                    (self.next_stream_id & 1))
                        if is_local:
                            max_stream_id = self.next_stream_id - 2
                        else:
                            max_stream_id = max_remote_stream_id
                        if frame.stream_id <= max_stream_id:
                            raise StreamError(
                                frame.stream_id,
                                constants.ErrorCode.STREAM_CLOSED)
                        else:
                            raise ConnectionError(
                                constants.ErrorCode.PROTOCOL_ERROR,
                                "non-existent stream")
                except StreamError as e:
                    yield self._write_frame(self._rst_stream_frame(
                        e.stream_id, e.code))
        except ConnectionError as e:
            # TODO: set last_stream_id
            yield self._write_frame(self._goaway_frame(
                e.code, 0, e.message))
            self.stream.close()
            return
        except GeneratorExit:
            # The generator is being garbage collected; don't close the
            # stream because the IOLoop is going away too.
            return
        except StreamClosedError:
            return
        except HTTPOutputError:
            # TODO: should these be caught somewhere else?
            self.stream.close()
            return
        except:
            gen_log.error("closing stream due to uncaught exception",
                          exc_info=True)
            self.stream.close()
            raise
        finally:
            if delegate is not None:
                delegate.on_close(self)

    def handle_frame(self, frame):
        if frame.type == constants.FrameType.SETTINGS:
            self._handle_settings_frame(frame)
        elif frame.type == constants.FrameType.WINDOW_UPDATE:
            self._handle_window_update_frame(frame)
        elif frame.type == constants.FrameType.PING:
            self._handle_ping_frame(frame)
        elif frame.type == constants.FrameType.GOAWAY:
            self.stream.close()
            # TODO: shut down all open streams.
            raise StreamClosedError()
        elif frame.type in (constants.FrameType.DATA,
                            constants.FrameType.HEADERS,
                            constants.FrameType.PRIORITY,
                            constants.FrameType.RST_STREAM,
                            constants.FrameType.PUSH_PROMISE,
                            constants.FrameType.CONTINUATION):
            raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                  "invalid frame type %s for stream 0" %
                                  frame.type)
        # Unknown frame types are silently discarded.

    def _write_frame(self, frame):
        logging.debug('sending frame %r', frame)
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
        if data_len > self._setting(constants.Setting.MAX_FRAME_SIZE):
            raise ConnectionError(constants.ErrorCode.FRAME_SIZE_ERROR)
        # Strip the reserved bit off of stream_id
        stream_id = stream_id & 0x7fffffff
        data = yield self.stream.read_bytes(data_len)
        raise gen.Return(Frame(typ, flags, stream_id, data))

    def _goaway_frame(self, error_code, last_stream_id, message):
        payload = struct.pack('>ii', last_stream_id, error_code.code)
        if message:
            payload = payload + utf8(message)
        return Frame(constants.FrameType.GOAWAY, 0, 0, payload)

    def _rst_stream_frame(self, stream_id, error_code):
        payload = struct.pack('>i', error_code.code)
        return Frame(constants.FrameType.RST_STREAM, 0, stream_id, payload)

    def _setting(self, setting):
        # TODO: respect changed settings.
        return setting.default

    def _settings_frame(self):
        # TODO: parameterize?
        if self.is_client:
            payload = struct.pack('>HI', constants.Setting.ENABLE_PUSH.code, 0)
        else:
            payload = b''
        return Frame(constants.FrameType.SETTINGS, 0, 0, payload)

    def _settings_ack_frame(self):
        return Frame(constants.FrameType.SETTINGS, constants.FrameFlag.ACK,
                     0, b'')

    def _handle_settings_frame(self, frame):
        if frame.flags & constants.FrameFlag.ACK:
            if frame.data:
                raise ConnectionError(constants.ErrorCode.FRAME_SIZE_ERROR,
                                      "SETTINGS ACK must be empty")
            return
        data = frame.data
        while data:
            if len(data) < 6:
                raise ConnectionError(
                    constants.ErrorCode.FRAME_SIZE_ERROR,
                    "SETTINGS frames must be multiples of 6 bytes")
            code, value = struct.unpack('>HI', data[:6])
            data = data[6:]
            # TODO: respect changed settings.
            if code == constants.Setting.ENABLE_PUSH.code:
                if value not in (0, 1):
                    raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                          "ENABLE_PUSH must be 0 or 1")
            elif code == constants.Setting.INITIAL_WINDOW_SIZE.code:
                if value > constants.MAX_WINDOW_SIZE:
                    raise ConnectionError(
                        constants.ErrorCode.FLOW_CONTROL_ERROR,
                        "INITIAL_WINDOW_SIZE too large")
            elif code == constants.Setting.MAX_FRAME_SIZE.code:
                if (value < constants.Setting.MAX_FRAME_SIZE.default or
                        value > constants.MAX_MAX_FRAME_SIZE):
                    raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                          "MAX_FRAME_SIZE out of bounds")
        self._write_frame(self._settings_ack_frame())

    def _handle_window_update_frame(self, frame):
        window_update = parse_window_update_frame(frame)
        if window_update == 0:
            raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                  "window update must not be zero")
        self.flow_window += window_update
        if self.flow_window > constants.MAX_WINDOW_SIZE:
            raise ConnectionError(constants.ErrorCode.FLOW_CONTROL_ERROR,
                                  "connection flow control limit too high")

    def _handle_ping_frame(self, frame):
        if frame.flags & constants.FrameFlag.ACK:
            return
        if len(frame.data) != 8:
            raise ConnectionError(constants.ErrorCode.FRAME_SIZE_ERROR)
        self._write_frame(Frame(constants.FrameType.PING,
                                constants.FrameFlag.ACK,
                                0, frame.data))
