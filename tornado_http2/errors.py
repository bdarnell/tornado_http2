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
