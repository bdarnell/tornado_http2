import collections
import os
from tornado.escape import utf8

from .constants import HeaderIndexMode
from .encoding import BitDecoder, BitEncoder


def _entry_size(name, value):
    return len(name) + len(value) + 32


class HpackDecoder(object):
    def __init__(self, dynamic_table_limit):
        self._dynamic_table = collections.deque()
        self._dynamic_table_size = 0
        self._dynamic_table_limit = dynamic_table_limit

    def decode(self, data):
        header_list = []
        bit_decoder = BitDecoder(data)
        while not bit_decoder.eod():
            is_indexed = bit_decoder.read_bit()
            if is_indexed:
                idx = bit_decoder.read_hpack_int()
                name, value = self.read_from_index(idx)
                header_list.append((name, value, HeaderIndexMode.YES))
            else:
                add_to_index = bit_decoder.read_bit()
                if add_to_index:
                    name, value = self.read_name_value_pair(bit_decoder)
                    header_list.append((name, value, HeaderIndexMode.YES))
                    self.add_to_dynamic_table(name, value)
                else:
                    is_limit_update = bit_decoder.read_bit()
                    if is_limit_update:
                        new_limit = bit_decoder.read_hpack_int()
                        # TODO: fail if new_limit is higher than old limit.
                        self._dynamic_table_limit = new_limit
                        self._gc_dynamic_table()
                    else:
                        if bit_decoder.read_bit():
                            mode = HeaderIndexMode.NEVER
                        else:
                            mode = HeaderIndexMode.NO
                        name, value = self.read_name_value_pair(bit_decoder)
                        header_list.append((name, value, mode))
        return header_list

    def read_name_value_pair(self, bit_decoder):
        name_index = bit_decoder.read_hpack_int()
        if name_index == 0:
            name = self.read_string(bit_decoder)
        else:
            name = self.read_from_index(name_index)[0]
        value = self.read_string(bit_decoder)
        assert name == name.lower()
        return name, value

    def read_string(self, bit_decoder):
        is_huffman = bit_decoder.read_bit()
        length = bit_decoder.read_hpack_int()
        if is_huffman:
            # read huffman chars until we have read 'length' bytes
            dest_byte = bit_decoder._byte_offset + length
            chars = []
            while bit_decoder._byte_offset < dest_byte:
                char = bit_decoder.read_huffman_char(dest_byte)
                if char is None:
                    break
                chars.append(char)
        else:
            chars = [bit_decoder.read_char() for i in range(length)]
        return bytes(bytearray(chars))

    def read_from_index(self, idx):
        if idx < len(_static_table):
            return _static_table[idx]
        else:
            return self._dynamic_table[idx - len(_static_table)]

    def add_to_dynamic_table(self, name, value):
        self._dynamic_table.appendleft((name, value))
        self._dynamic_table_size += _entry_size(name, value)
        self._gc_dynamic_table()

    def _gc_dynamic_table(self):
        while self._dynamic_table_size > self._dynamic_table_limit:
            name, value = self._dynamic_table.pop()
            self._dynamic_table_size -= _entry_size(name, value)


class HpackEncoder(object):
    def __init__(self, dynamic_table_limit, encode_huffman=False):
        self._dynamic_table_limit = dynamic_table_limit
        self._encode_huffman = encode_huffman
        self._dynamic_table = collections.deque()
        self._dynamic_table_size = 0

    def encode(self, header_list):
        bit_encoder = BitEncoder()
        for k, v, mode in header_list:
            k = k.lower()
            self.write_header(bit_encoder, k, v, mode)
        return bit_encoder.data()

    def find_pair_index(self, pair):
        idx = _static_pairs.get(pair)
        if idx:
            return idx
        for i, p in enumerate(self._dynamic_table):
            if pair == p:
                return i + len(_static_table)
        return None

    def find_key_index(self, key):
        idx = _static_keys.get(key)
        if idx:
            return idx
        for i, k in enumerate(self._dynamic_table):
            if k == key:
                return i + len(_static_table)
        return None

    def write_header(self, bit_encoder, k, v, mode):
        idx = self.find_pair_index((k, v))
        if idx:
            bit_encoder.write_bit(1)
            bit_encoder.write_hpack_int(idx)
            return
        if mode == HeaderIndexMode.YES:
            self.add_to_dynamic_table(k, v)
            bit_encoder.write_bits(0, 1)
        elif mode == HeaderIndexMode.NEVER:
            bit_encoder.write_bits(0, 0, 0, 1)
        else:
            bit_encoder.write_bits(0, 0, 0, 0)
        idx = self.find_key_index(k)
        if idx:
            bit_encoder.write_hpack_int(idx)
        else:
            bit_encoder.write_hpack_int(0)
            self.write_string(bit_encoder, k)
        self.write_string(bit_encoder, v)

    def write_string(self, bit_encoder, s):
        bit_encoder.write_bit(self._encode_huffman)
        if self._encode_huffman:
            enc = BitEncoder()
            enc.write_huffman_string(s)
            s = enc.data()
        bit_encoder.write_hpack_int(len(s))
        bit_encoder.write_string(s)

    def add_to_dynamic_table(self, k, v):
        self._dynamic_table.appendleft((k, v))
        self._dynamic_table_size += _entry_size(k, v)
        self._gc_dynamic_table()

    def _gc_dynamic_table(self):
        while self._dynamic_table_size > self._dynamic_table_limit:
            name, value = self._dynamic_table.pop()
            self._dynamic_table_size -= _entry_size(name, value)


def _load_static_table():
    """Parses the hpack static table, which was copied from
    http://http2.github.io/http2-spec/compression.html#static.table
    corresponding to
    http://tools.ietf.org/html/draft-ietf-httpbis-header-compression-12#appendix-A
    """
    # start the table with a dummy entry 0
    table = [None]
    with open(os.path.join(os.path.dirname(__file__),
                           'hpack_static_table.txt')) as f:
        for line in f:
            if not line:
                continue
            fields = line.split('\t')
            if int(fields[0]) != len(table):
                raise ValueError("inconsistent numbering in static table")
            name = utf8(fields[1].strip())
            value = utf8(fields[2].strip()) if len(fields) > 2 else None
            table.append((name, value))
    static_keys = {}
    static_pairs = {}
    for i, pair in enumerate(table):
        if pair is None:
            continue
        if pair[0] not in static_keys:
            # For repeated keys, prefer the earlier one.
            static_keys[pair[0]] = i
        static_pairs[pair] = i
    return table, static_keys, static_pairs

_static_table, _static_keys, _static_pairs = _load_static_table()
