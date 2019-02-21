import functools
import struct

from tornado.concurrent import Future
from tornado.escape import native_str, utf8
from tornado import gen
from tornado.http1connection import _GzipMessageDelegate
from tornado.httputil import HTTPHeaders, HTTPOutputError, RequestStartLine, ResponseStartLine, responses
from tornado.ioloop import IOLoop
from tornado.locks import Lock

from . import constants
from .errors import ConnectionError, StreamError
from .flow_control import Window
from .frames import Frame, parse_window_update_frame
from .hpack import HpackError


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
        self.write_lock = Lock()
        from tornado.util import ObjectDict
        # TODO: remove
        self.stream = ObjectDict(io_loop=IOLoop.current(), close=conn.stream.close)
        self._incoming_content_remaining = None
        self._outgoing_content_remaining = None
        self._delegate_started = False
        self.window = Window(conn.window, stream_id,
                             conn.setting(constants.Setting.INITIAL_WINDOW_SIZE))
        self._header_frames = []
        self._phase = constants.HTTPPhase.HEADERS

    def set_delegate(self, delegate):
        self.orig_delegate = self.delegate = delegate
        if self.conn.params.decompress:
            self.delegate = _GzipMessageDelegate(delegate, self.conn.params.chunk_size)

    def handle_frame(self, frame):
        if frame.type == constants.FrameType.PRIORITY:
            self._handle_priority_frame(frame)
            return
        elif frame.type == constants.FrameType.RST_STREAM:
            self._handle_rst_stream_frame(frame)
            return
        elif frame.type == constants.FrameType.WINDOW_UPDATE:
            self._handle_window_update_frame(frame)
            return
        elif frame.type in (constants.FrameType.SETTINGS,
                            constants.FrameType.GOAWAY,
                            constants.FrameType.PUSH_PROMISE):
            raise Exception("invalid frame type %s for stream", frame.type)

        if self.finish_future.done():
            raise StreamError(self.stream_id, constants.ErrorCode.STREAM_CLOSED)

        if frame.type == constants.FrameType.HEADERS:
            self._handle_headers_frame(frame)
        elif frame.type == constants.FrameType.CONTINUATION:
            self._handle_continuation_frame(frame)
        elif frame.type == constants.FrameType.DATA:
            self._handle_data_frame(frame)
        # Unknown frame types are silently discarded, unless they break
        # the rule that nothing can come between HEADERS and CONTINUATION.

    def needs_continuation(self):
        return bool(self._header_frames)

    def _handle_headers_frame(self, frame):
        if self._phase == constants.HTTPPhase.BODY:
            self._phase = constants.HTTPPhase.TRAILERS
        frame = frame.without_padding()
        self._header_frames.append(frame)
        self._check_header_length()
        if frame.flags & constants.FrameFlag.END_HEADERS:
            self._parse_headers()

    def _handle_continuation_frame(self, frame):
        if not self._header_frames:
            raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                  "CONTINUATION without HEADERS")
        self._header_frames.append(frame)
        self._check_header_length()
        if frame.flags & constants.FrameFlag.END_HEADERS:
            self._parse_headers()

    def _check_header_length(self):
        if (sum(len(f.data) for f in self._header_frames) >
                self.conn.params.max_header_size):
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

    def _parse_headers(self):
        frame = self._header_frames[0]
        data = b''.join(f.data for f in self._header_frames)
        self._header_frames = []
        if frame.flags & constants.FrameFlag.PRIORITY:
            # TODO: support PRIORITY and PADDING.
            # This is just enough to cover an error case tested in h2spec.
            stream_dep, weight = struct.unpack('>ib', data[:5])
            data = data[5:]
            # strip off the "exclusive" bit
            stream_dep = stream_dep & 0x7fffffff
            if stream_dep == frame.stream_id:
                raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                      "stream cannot depend on itself")
        pseudo_headers = {}
        headers = HTTPHeaders()
        try:
            # Pseudo-headers must come before any regular headers,
            # and only in the first HEADERS phase.
            has_regular_header = bool(self._phase == constants.HTTPPhase.TRAILERS)
            for k, v, idx in self.conn.hpack_decoder.decode(bytearray(data)):
                if k != k.lower():
                    # RFC section 8.1.2
                    raise StreamError(self.stream_id,
                                      constants.ErrorCode.PROTOCOL_ERROR)
                if k.startswith(b':'):
                    if self.conn.is_client:
                        valid_pseudo_headers = (b':status',)
                    else:
                        valid_pseudo_headers = (b':method', b':scheme',
                                                b':authority', b':path')
                    if (has_regular_header or
                            k not in valid_pseudo_headers or
                            native_str(k) in pseudo_headers):
                        raise StreamError(self.stream_id,
                                          constants.ErrorCode.PROTOCOL_ERROR)
                    pseudo_headers[native_str(k)] = native_str(v)
                    if k == b":authority":
                        headers.add("Host", native_str(v))
                else:
                    headers.add(native_str(k),  native_str(v))
                    has_regular_header = True
        except HpackError:
            raise ConnectionError(constants.ErrorCode.COMPRESSION_ERROR)
        if self._phase == constants.HTTPPhase.HEADERS:
            self._start_request(pseudo_headers, headers)
        elif self._phase == constants.HTTPPhase.TRAILERS:
            # TODO: support trailers
            pass
        if (not self._maybe_end_stream(frame.flags) and
                self._phase == constants.HTTPPhase.TRAILERS):
            # The frame that finishes the trailers must also finish
            # the stream.
            raise StreamError(self.stream_id, constants.ErrorCode.PROTOCOL_ERROR)

    def _start_request(self, pseudo_headers, headers):
        if "connection" in headers:
            raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                  "connection header should not be present")
        if "te" in headers and headers["te"] != "trailers":
            raise StreamError(self.stream_id, constants.ErrorCode.PROTOCOL_ERROR)
        if self.conn.is_client:
            status = int(pseudo_headers[':status'])
            start_line = ResponseStartLine('HTTP/2.0', status, responses.get(status, ''))
        else:
            for k in (':method', ':scheme', ':path'):
                if k not in pseudo_headers:
                    raise StreamError(self.stream_id,
                                      constants.ErrorCode.PROTOCOL_ERROR)
            start_line = RequestStartLine(pseudo_headers[':method'],
                                          pseudo_headers[':path'], 'HTTP/2.0')
            self._request_start_line = start_line

        if (self.conn.is_client and
            (self._request_start_line.method == 'HEAD' or
             start_line.code == 304)):
            self._incoming_content_remaining = 0
        elif "content-length" in headers:
            self._incoming_content_remaining = int(headers["content-length"])

        if not self.conn.is_client or status >= 200:
            self._phase = constants.HTTPPhase.BODY

        self._delegate_started = True
        self.delegate.headers_received(start_line, headers)

    def _handle_data_frame(self, frame):
        if self._header_frames:
            raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                  "DATA without END_HEADERS")
        if self._phase == constants.HTTPPhase.TRAILERS:
            raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                  "DATA after trailers")
        self._phase = constants.HTTPPhase.BODY
        frame = frame.without_padding()
        if self._incoming_content_remaining is not None:
            self._incoming_content_remaining -= len(frame.data)
            if self._incoming_content_remaining < 0:
                raise StreamError(self.stream_id, constants.ErrorCode.PROTOCOL_ERROR)
        if frame.data and self._delegate_started:
            future = self.delegate.data_received(frame.data)
            if future is None:
                self._send_window_update(len(frame.data))
            else:
                IOLoop.current().add_future(
                    future, lambda f: self._send_window_update(len(frame.data)))
        self._maybe_end_stream(frame.flags)

    def _send_window_update(self, amount):
        encoded = struct.pack('>I', amount)
        for stream_id in (0, self.stream_id):
            self.conn._write_frame(Frame(
                constants.FrameType.WINDOW_UPDATE, 0,
                stream_id, encoded))

    def _maybe_end_stream(self, flags):
        if flags & constants.FrameFlag.END_STREAM:
            if (self._incoming_content_remaining is not None and
                    self._incoming_content_remaining != 0):
                raise StreamError(self.stream_id, constants.ErrorCode.PROTOCOL_ERROR)
            if self._delegate_started:
                self._delegate_started = False
                self.delegate.finish()
            self.finish_future.set_result(None)
            return True
        return False

    def _handle_priority_frame(self, frame):
        # TODO: implement priority
        if len(frame.data) != 5:
            raise StreamError(self.stream_id,
                              constants.ErrorCode.FRAME_SIZE_ERROR)

    def _handle_rst_stream_frame(self, frame):
        if len(frame.data) != 4:
            raise ConnectionError(constants.ErrorCode.FRAME_SIZE_ERROR)
        # TODO: expose error code?
        if self._delegate_started:
            self.delegate.on_connection_close()

    def _handle_window_update_frame(self, frame):
        self.window.apply_window_update(frame)

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
            self._outgoing_content_remaining = 0
        elif 'Content-Length' in headers:
            self._outgoing_content_remaining = int(headers['Content-Length'])
        header_list = []
        if self.conn.is_client:
            self._request_start_line = start_line
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
            k = utf8(k.lower())
            if k == b"connection":
                # Remove the implicit "connection: close", which is not
                # allowed in http2.
                # TODO: move the responsibility for this from httpclient
                # to http1connection?
                continue
            header_list.append((k, utf8(v),
                                constants.HeaderIndexMode.YES))
        data = bytes(self.conn.hpack_encoder.encode(header_list))
        frame = Frame(constants.FrameType.HEADERS,
                      constants.FrameFlag.END_HEADERS, self.stream_id,
                      data)
        self.conn._write_frame(frame)

        return self.write(chunk, callback)

    @_reset_on_error
    def write(self, chunk, callback=None):
        if chunk:
            if self._outgoing_content_remaining is not None:
                self._outgoing_content_remaining -= len(chunk)
                if self._outgoing_content_remaining < 0:
                    raise HTTPOutputError(
                        "Tried to write more data than Content-Length")
        return self._write_chunk(chunk, callback)

    @gen.coroutine
    def _write_chunk(self, chunk, callback=None):
        try:
            if chunk:
                yield self.write_lock.acquire()
                while chunk:
                    bytes_to_write = min(len(chunk), self.conn.setting(
                        constants.Setting.MAX_FRAME_SIZE))
                    allowance = yield self.window.consume(bytes_to_write)

                    yield self.conn._write_frame(
                        Frame(constants.FrameType.DATA, 0,
                              self.stream_id, chunk[:allowance]))
                    chunk = chunk[allowance:]
                self.write_lock.release()
            if callback is not None:
                callback()
        except Exception:
            self.reset()
            raise

    @_reset_on_error
    def finish(self):
        if (self._outgoing_content_remaining is not None and
                self._outgoing_content_remaining != 0):
            raise HTTPOutputError(
                "Tried to write %d bytes less than Content-Length" %
                self._outgoing_content_remaining)
        return self._write_end_stream()

    @gen.coroutine
    def _write_end_stream(self):
        # Callers are not required to wait for write() before calling finish,
        # so we must manually lock.
        yield self.write_lock.acquire()
        try:
            self.conn._write_frame(Frame(constants.FrameType.DATA,
                                         constants.FrameFlag.END_STREAM,
                                         self.stream_id, b''))
        except Exception:
            self.reset()
            raise
        finally:
            self.write_lock.release()

    def read_response(self, delegate):
        assert delegate is self.orig_delegate, 'cannot change delegate'
        return self.finish_future
