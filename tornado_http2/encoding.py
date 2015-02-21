from collections import defaultdict
import os
import re

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

        http://tools.ietf.org/html/draft-ietf-httpbis-header-compression-12#section-5.1
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

    def write_huffman_char(self, c):
        # TODO: optimize this.
        for b in _huffman_map[c]:
            self.write_bit(b)

class BitDecoder(object):
    def __init__(self, data):
        """
        In python 3, data may be of type bytes or bytearray; in python 2
        it may only be bytearray.
        """
        self._data = data
        self._byte_offset = 0
        self._bit_offset = 0

    def eod(self):
        return self._byte_offset >= len(self._data)

    def read_bit(self):
        if self.eod():
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

    def read_huffman_char(self, limit):
        """Reads one huffman-encoded character from the stream.

        Will not read past ``limit`` bytes. ``limit`` may be None to
        use the entire decoder. Returns None for end-of-stream.
        """
        if limit is None:
            limit = len(self._data)
        tree_node = _huffman_tree
        while self._byte_offset < limit:
            tree_node = tree_node[self.read_bit()]
            if not isinstance(tree_node, dict):
                return tree_node
        # End-of-stream.
        # TODO: it is an error to reach this point if we are not aligned
        # at the end of a byte or if any of the bits read in this call were
        # zero. Verify this.
        return None

    def read_char(self):
        assert self._bit_offset == 0
        ch = self._data[self._byte_offset]
        self._byte_offset += 1
        return ch

def _tree():
    return defaultdict(_tree)

def _load_huffman_data():
    """Parses hpack_huffman_data, which was copied from
    http://http2.github.io/http2-spec/compression.html#huffman.code
    (corresponding to
    http://tools.ietf.org/html/draft-ietf-httpbis-header-compression-12#appendix-B )

    Implements a very crude and inefficient huffman codec.
    """
    huffman_map = {}
    huffman_tree = _tree()
    with open(os.path.join(os.path.dirname(__file__),
                           'hpack_huffman_data.txt')) as f:
        line_re = re.compile(
            r"(?:   |EOS|'(.)') \(([ 0-9]{3})\)  ([|01]+) +([0-9a-f]+)  \[([ 0-9]{2})\]")
        for line in f:
            m = line_re.match(line)
            ch, i, bits, hx, bit_len = m.groups()
            i = int(i.strip())
            bits = [int(c) for c in bits if c != '|']
            bit_len = int(bit_len.strip())
            if ch is not None and ord(ch) != i:
                raise ValueError("ord(%s) == %d, not %d", ch, ord(ch), i)
            if len(bits) != bit_len:
                raise ValueError("len(bits) == %d, not %d", len(bits), bit_len)
            if i == 256:
                # Skip the end-of-stream marker for now.
                continue
            if isinstance(chr(i), type(b'')):
                key = chr(i)
            else:
                key = i
            if key in huffman_map:
                raise ValueError("chr(%d) already in map", i)
            huffman_map[key] = bits
            tree_node = huffman_tree
            for b in bits[:-1]:
                tree_node = tree_node[b]
            tree_node[bits[-1]] = key
    return huffman_map, huffman_tree

_huffman_map, _huffman_tree = _load_huffman_data()
