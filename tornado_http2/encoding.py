class EODError(Exception):
    pass

class BitEncoder(object):
    def __init__(self):
        self._data = bytearray()
        self._bit_offset = 8

    def data(self):
        return self._data

    def write_bit(self, b):
        if self._bit_offset > 7:
            self._data.append(0)
            self._bit_offset = 0
        self._data[-1] |= b << (7 - self._bit_offset)
        self._bit_offset += 1

    def write_hpack_int(self, i):
        """Encodes an integer as defined by HPACK.

        http://tools.ietf.org/html/draft-ietf-httpbis-header-compression-08#section-6.1
        """
        n = 8 - self._bit_offset
        if n == 0:
            self._data.append(0)
            n = 8
        if i < (1 << n) - 1:
            self._data[-1] |= i
            self._bit_offset = 8
            return
        self._data[-1] |= (1 << n) - 1
        self._bit_offset = 8
        i -= (1 << n) - 1
        while i >= 128:
            self._data.append((i & 127) + 128)
            i >>= 7
        self._data.append(i)

class BitDecoder(object):
    def __init__(self, data):
        """
        In python 3, data may be of type bytes or bytearray; in python 2
        it may only be bytearray.
        """
        self._data = data
        self._byte_offset = 0
        self._bit_offset = 0

    def read_bit(self):
        if self._byte_offset >= len(self._data):
            raise EODError()
        mask = 1 << (7 - self._bit_offset)
        bit = self._data[self._byte_offset] & mask
        bit >>= (7 - self._bit_offset)
        self._bit_offset += 1
        if self._bit_offset > 7:
            self._byte_offset += 1
            self._bit_offset = 0
        return bit

    def read_hpack_int(self):
        prefix_mask = (1 << (8 - self._bit_offset)) - 1
        i = self._data[self._byte_offset] & prefix_mask
        self._bit_offset = 0
        self._byte_offset += 1
        if i < prefix_mask:
            return i
        m = 0
        while True:
            b = self._data[self._byte_offset]
            self._byte_offset += 1
            i += (b & 0x7f) << m
            m += 7
            if not (b & 0x80):
                break
        return i
