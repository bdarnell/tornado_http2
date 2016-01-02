import binascii

try:
    import enum
except ImportError:
    import enum34 as enum

# ALPN protocol identifiers:
# https://httpwg.github.io/specs/rfc7540.html#iana-alpn
HTTP2_TLS = "h2"
HTTP2_CLEAR = "h2c"

# Defined in https://tools.ietf.org/html/draft-ietf-httpbis-http2-17#section-3.5
CLIENT_PREFACE = binascii.a2b_hex("505249202a20485454502f322e300d0a0d0a534d0d0a0d0a")


class FrameType(enum.IntEnum):
    """Constants for HTTP2 frame types.

    Defined in
    https://tools.ietf.org/html/draft-ietf-httpbis-http2-17#section-11.2
    """
    DATA = 0x0
    HEADERS = 0x1
    PRIORITY = 0x2
    RST_STREAM = 0x3
    SETTINGS = 0x4
    PUSH_PROMISE = 0x5
    PING = 0x6
    GOAWAY = 0x7
    WINDOW_UPDATE = 0x8
    CONTINUATION = 0x9


class Setting(enum.Enum):
    """Constants for HTTP2 setting fields.

    Defined in
    https://tools.ietf.org/html/draft-ietf-httpbis-http2-17#section-11.3
    """
    def __init__(self, code, default):
        self.code = code
        self.default = default

    HEADER_TABLE_SIZE = (0x1, 4096)
    ENABLE_PUSH = (0x2, 1)
    MAX_CONCURRENT_STREAMS = (0x3, None)
    INITIAL_WINDOW_SIZE = (0x4, 65535)
    MAX_FRAME_SIZE = (0x5, 16384)
    MAX_HEADER_LIST_SIZE = (0x6, None)

MAX_WINDOW_SIZE = 2**31 - 1
MAX_MAX_FRAME_SIZE = 2**24 - 1

class ErrorCode(enum.Enum):
    """Constants for HTTP2 error codes.

    Defined in
    https://tools.ietf.org/html/draft-ietf-httpbis-http2-17#section-11.4
    """
    def __init__(self, code, description):
        self.code = code
        self.description = description

    NO_ERROR = (0x0, "Graceful shutdown")
    PROTOCOL_ERROR = (0x1, "Protocol error detected")
    INTERNAL_ERROR = (0x2, "Implementation fault")
    FLOW_CONTROL_ERROR = (0x3, "Flow control limits exceeded")
    SETTINGS_TIMEOUT = (0x4, "Settings not acknowledged")
    STREAM_CLOSED = (0x5, "Frame received for closed stream")
    FRAME_SIZE_ERROR = (0x6, "Frame size incorrect")
    REFUSED_STREAM = (0x7, "Stream not processed")
    CANCEL = (0x8, "Stream cancelled")
    COMPRESSION_ERROR = (0x9, "Compression state not updated")
    CONNECT_ERROR = (0xa, "TCP connection error for CONNECT method")
    ENHANCE_YOUR_CALM = (0xb, "Processing capacity  exceeded")
    INADEQUATE_SECURITY = (0xc, "Negotiated TLS parameters not acceptable")
    HTTP_1_1_REQUIRED = (0xd, "Use HTTP/1.1 for the request")


class HeaderIndexMode(enum.Enum):
    """Flags for the HPACK encoder.
    """
    YES = 1
    NO = 2
    NEVER = 3


class StreamState(enum.Enum):
    """States for an HTTP2 stream.
    """
    IDLE = 0
    RESERVED_LOCAL = 1
    RESERVED_REMOTE = 2
    OPEN = 3
    HALF_CLOSED_LOCAL = 4
    HALF_CLOSED_REMOTE = 5
    CLOSED = 6


class FrameFlag(enum.IntEnum):
    """HTTP2 frame-level flags.

    Flags are combined with bitwise OR.
    Note that the set of valid flags varies by frame type.
    """
    END_STREAM = 0x1  # DATA, HEADERS
    ACK = 0x1  # SETTINGS, PING
    END_HEADERS = 0x4  # HEADERS, PUSH_PROMISE, CONTINUATION
    PADDED = 0x8  # DATA, HEADERS, PUSH_PROMISE
    PRIORITY = 0x20  # HEADERS
