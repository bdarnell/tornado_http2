import collections
import logging
import struct

from tornado.concurrent import Future
from tornado.escape import native_str, utf8
from tornado import gen
from tornado.http1connection import _GzipMessageDelegate
from tornado.httputil import HTTPHeaders, RequestStartLine, ResponseStartLine, responses, HTTPOutputError
from tornado.ioloop import IOLoop
from tornado.iostream import StreamClosedError
from tornado.log import gen_log

from . import constants
from .hpack import HpackDecoder, HpackEncoder, HpackError


class Params(object):
    def __init__(self, chunk_size=None, max_header_size=None, decompress=False):
        self.chunk_size = chunk_size or 65536
        self.max_header_size = max_header_size or 65536
        self.decompress = decompress


class Frame(collections.namedtuple(
        'Frame', ['type', 'flags', 'stream_id', 'data'])):
    def without_padding(self):
        """Returns a new Frame, equal to this one with any padding removed."""
        if self.flags & constants.FrameFlag.PADDED:
            pad_len, = struct.unpack('>b', self.data[:1])
            if pad_len > (len(self.data)-1):
                if self.type == constants.FrameType.HEADERS:
                    raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR)
                raise StreamError(self.stream_id,
                                  constants.ErrorCode.PROTOCOL_ERROR)
            data = self.data[1:-pad_len]
            return Frame(self.type, self.flags, self.stream_id, data)
        return self


class ConnectionError(Exception):
    """A protocol-level error which shuts down the entire connection."""
    def __init__(self, code, message=None):
        self.code = code
        self.message = message


class StreamError(Exception):
    """An error which terminates a stream but leaves the connection intact."""
    def __init__(self, stream_id, code):
        self.stream_id = stream_id
        self.code = code


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
            while True:
                try:
                    frame = yield self._read_frame()
                    if frame is None:
                        # discard unknown frames
                        continue
                    logging.debug('got frame %r', frame)
                    if frame.stream_id == 0:
                        self.handle_frame(frame)
                    elif frame.stream_id in self.streams:
                        self.streams[frame.stream_id].handle_frame(frame)
                    elif (not self.is_client and
                          frame.type == constants.FrameType.HEADERS):
                        if (frame.stream_id & 1) == (self.next_stream_id & 1):
                            # The remote is trying to use our local keyspace
                            raise ConnectionError(
                                constants.ErrorCode.PROTOCOL_ERROR)
                        if frame.stream_id > max_remote_stream_id:
                            max_remote_stream_id = frame.stream_id
                        stream = Stream(self, frame.stream_id, None,
                                        context=self.context)
                        stream.set_delegate(delegate.start_request(self, stream))
                        self.streams[frame.stream_id] = stream
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
                                constants.ErrorCode.PROTOCOL_ERROR)
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
            # TODO: handle WINDOW_UPDATE
            pass
        elif frame.type == constants.FrameType.PING:
            self._handle_ping_frame(frame)
        else:
            raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                  "invalid frame type %s for stream 0" %
                                  frame.type)

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
        try:
            typ = constants.FrameType(typ)
        except ValueError:
            return None
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

    def _handle_ping_frame(self, frame):
        if frame.flags & constants.FrameFlag.ACK:
            return
        if len(frame.data) != 8:
            raise ConnectionError(constants.ErrorCode.FRAME_SIZE_ERROR)
        self._write_frame(Frame(constants.FrameType.PING,
                                constants.FrameFlag.ACK,
                                0, frame.data))


def _reset_on_error(f):
    def wrapper(self, *args, **kw):
        try:
            return f(self, *args, **kw)
        except Exception:
            self.reset()
            raise
    return wrapper


class Stream(object):
    def __init__(self, conn, stream_id, delegate, context=None):
        self.conn = conn
        self.stream_id = stream_id
        self.set_delegate(delegate)
        self.context = context
        self.finish_future = Future()
        from tornado.util import ObjectDict
        # TODO: remove
        self.stream = ObjectDict(io_loop=IOLoop.current(), close=conn.stream.close)
        self._expected_content_remaining = None
        self._delegate_started = False

    def set_delegate(self, delegate):
        self.orig_delegate = self.delegate = delegate
        if self.conn.params.decompress:
            self.delegate = _GzipMessageDelegate(delegate, self.conn.params.chunk_size)

    def handle_frame(self, frame):
        if self.finish_future.done():
            raise StreamError(self.stream_id, constants.ErrorCode.STREAM_CLOSED)
        if frame.type == constants.FrameType.HEADERS:
            self._handle_headers_frame(frame)
        elif frame.type == constants.FrameType.DATA:
            self._handle_data_frame(frame)
        elif frame.type == constants.FrameType.PRIORITY:
            self._handle_priority_frame(frame)
        elif frame.type == constants.FrameType.RST_STREAM:
            self._handle_rst_stream_frame(frame)
        else:
            raise Exception("invalid frame type %s", frame.type)

    def _handle_headers_frame(self, frame):
        if not (frame.flags & constants.FrameFlag.END_HEADERS):
            raise Exception("Continuation frames not yet supported")
        frame = frame.without_padding()
        data = frame.data
        if len(data) > self.conn.params.max_header_size:
            if self.conn.is_client:
                # TODO: Need tests for client side of headers-too-large.
                # What's the best way to send an error?
                self.delegate.on_connection_close()
            else:
                # write_headers needs a start line so it can tell
                # whether this is a HEAD or not. If we're rejecting
                # the headers we can't know so just make something up.
                # Note that this means the error response body MUST be
                # zero bytes so it doesn't matter whether the client
                # sent a HEAD or a GET.
                self._request_start_line = RequestStartLine('GET', '/', 'HTTP/2.0')
                start_line = ResponseStartLine('HTTP/2.0', 431, 'Headers too large')
                self.write_headers(start_line, HTTPHeaders())
                self.finish()
            return
        if frame.flags & constants.FrameFlag.PRIORITY:
            # TODO: support PRIORITY and PADDING.
            # This is just enough to cover an error case tested in h2spec.
            stream_dep, weight = struct.unpack('>ib', data[:5])
            data = data[5:]
            # strip off the "exclusive" bit
            stream_dep = stream_dep & 0x7fffffff
            if stream_dep == frame.stream_id:
                raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR)
        pseudo_headers = {}
        headers = HTTPHeaders()
        try:
            for k, v, idx in self.conn.hpack_decoder.decode(bytearray(data)):
                if k == b":authority":
                    headers.add("Host", native_str(v))
                if k.startswith(b':'):
                    pseudo_headers[native_str(k)] = native_str(v)
                else:
                    headers.add(native_str(k),  native_str(v))
        except HpackError:
            raise ConnectionError(constants.ErrorCode.COMPRESSION_ERROR)
        if self.conn.is_client:
            status = int(pseudo_headers[':status'])
            start_line = ResponseStartLine('HTTP/2.0', status, responses.get(status, ''))
        else:
            start_line = RequestStartLine(pseudo_headers[':method'],
                                          pseudo_headers[':path'], 'HTTP/2.0')
        self._request_start_line = start_line

        self._delegate_started = True
        self.delegate.headers_received(start_line, headers)
        if frame.flags & constants.FrameFlag.END_STREAM:
            self.delegate.finish()
            self.finish_future.set_result(None)

    def _handle_data_frame(self, frame):
        frame = frame.without_padding()
        if frame.data and self._delegate_started:
            self.delegate.data_received(frame.data)
        if frame.flags & constants.FrameFlag.END_STREAM:
            if self._delegate_started:
                self._delegate_started = False
                self.delegate.finish()
            self.finish_future.set_result(None)

    def _handle_priority_frame(self, frame):
        # TODO: implement priority
        if len(frame.data) != 5:
            raise StreamError(self.stream_id,
                              constants.ErrorCode.FRAME_SIZE_ERROR)

    def _handle_rst_stream_frame(self, frame):
        if self._delegate_started:
            self.delegate.on_connection_close()

    def set_close_callback(self, callback):
        # TODO: this shouldn't be necessary
        pass

    def reset(self):
        self.conn._write_frame(Frame(constants.FrameType.RST_STREAM,
                                     0, self.stream_id, b'\x00\x00\x00\x00'))

    @_reset_on_error
    def write_headers(self, start_line, headers, chunk=None, callback=None):
        if (not self.conn.is_client and
            (self._request_start_line.method == 'HEAD' or
             start_line.code == 304)):
            self._expected_content_remaining = 0
        elif 'Content-Length' in headers:
            self._expected_content_remaining = int(headers['Content-Length'])
        header_list = []
        if self.conn.is_client:
            header_list.append((b':method', utf8(start_line.method),
                                constants.HeaderIndexMode.YES))
            header_list.append((b':scheme', b'https',
                                constants.HeaderIndexMode.YES))
            header_list.append((b':path', utf8(start_line.path),
                                constants.HeaderIndexMode.NO))
        else:
            header_list.append((b':status', utf8(str(start_line.code)),
                                constants.HeaderIndexMode.YES))
        for k, v in headers.get_all():
            header_list.append((utf8(k.lower()), utf8(v),
                                constants.HeaderIndexMode.YES))
        data = bytes(self.conn.hpack_encoder.encode(header_list))
        frame = Frame(constants.FrameType.HEADERS,
                      constants.FrameFlag.END_HEADERS, self.stream_id,
                      data)
        self.conn._write_frame(frame)

        return self.write(chunk, callback=callback)

    @_reset_on_error
    def write(self, chunk, callback=None):
        if chunk:
            if self._expected_content_remaining is not None:
                self._expected_content_remaining -= len(chunk)
                if self._expected_content_remaining < 0:
                    raise HTTPOutputError(
                        "Tried to write more data than Content-Length")
            self.conn._write_frame(Frame(constants.FrameType.DATA, 0,
                                         self.stream_id, chunk))
        # TODO: flow control
        if callback is not None:
            callback()
        else:
            future = Future()
            future.set_result(None)
            return future

    @_reset_on_error
    def finish(self):
        if (self._expected_content_remaining is not None and
                self._expected_content_remaining != 0):
            raise HTTPOutputError(
                "Tried to write %d bytes less than Content-Length" %
                self._expected_content_remaining)
        self.conn._write_frame(Frame(constants.FrameType.DATA,
                                     constants.FrameFlag.END_STREAM,
                                     self.stream_id, b''))

    def read_response(self, delegate):
        assert delegate is self.orig_delegate, 'cannot change delegate'
        return self.finish_future
