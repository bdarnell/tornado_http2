import collections
import struct

from . import constants
from .errors import ConnectionError, StreamError


class Frame(collections.namedtuple(
        'Frame', ['type', 'flags', 'stream_id', 'data'])):
    def without_padding(self):
        """Returns a new Frame, equal to this one with any padding removed."""
        if self.flags & constants.FrameFlag.PADDED:
            pad_len, = struct.unpack('>b', self.data[:1])
            if pad_len > (len(self.data)-1):
                if self.type == constants.FrameType.HEADERS:
                    raise ConnectionError(constants.ErrorCode.PROTOCOL_ERROR,
                                          "invalid padding length")
                raise StreamError(self.stream_id,
                                  constants.ErrorCode.PROTOCOL_ERROR)
            data = self.data[1:-pad_len]
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
