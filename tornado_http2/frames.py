import collections
import struct

from . import constants
from .errors import ConnectionError, StreamError


class Frame(collections.namedtuple(
        'Frame', ['type', 'flags', 'stream_id', 'data'])):
    def without_padding(self):
        """Returns a new Frame, equal to this one with any padding removed."""
        if self.flags & constants.FrameFlag.PADDED:
            if not self.data:
                raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                      "missing padding length")
            pad_len = self.data[0]
            if pad_len >= len(self.data):
                raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                      "invalid padding length")
            data = self.data[1:len(self.data) - pad_len]
            return Frame(self.type, self.flags, self.stream_id, data)
        return self


def parse_window_update_frame(frame):
    try:
        window_update, = struct.unpack('>I', frame.data)
    except struct.error:
        raise ConnectionError(constants.ErrorCode.FRAME_SIZE_ERROR,
                              "WINDOW_UPDATE incorrect size")
    # strip reserved bit
    window_update = window_update & 0x7fffffff
    return window_update
