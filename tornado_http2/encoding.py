class EODError(Exception):
    pass

class BitEncoder(object):
    def __init__(self):
        self._data = bytearray()
        self._bit_offset = 8

    def write_bit(self, b):
        if self._bit_offset > 7:
            self._data.append(0)
            self._bit_offset = 0
        self._data[-1] |= b << (7 - self._bit_offset)
        self._bit_offset += 1

    def data(self):
        return self._data

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
