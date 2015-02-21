import collections
import os
from tornado.escape import utf8

from .encoding import BitDecoder, EODError

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
                header_list.append((name, value))
            else:
                add_to_index = bit_decoder.read_bit()
                if add_to_index:
                    name, value = self.read_name_value_pair(bit_decoder)
                    header_list.append((name, value))
                    self.add_to_dynamic_table(name, value)
                else:
                    is_limit_update = bit_decoder.read_bit()
                    if is_limit_update:
                        new_limit = bit_decoder.read_hpack_int()
                        # TODO: fail if new_limit is higher than old limit.
                        self._dynamic_table_limit = new_limit
                    else:
                        # read the never-index bit and discard for now.
                        bit_decoder.read_bit()
                        header_list.append(self.read_name_value_pair(bit_decoder))
        return header_list

    def read_name_value_pair(self, bit_decoder):
        name_index = bit_decoder.read_hpack_int()
        if name_index == 0:
            name = self.read_string(bit_decoder)
        else:
            name = self.read_from_index(name_index)[0]
        value = self.read_string(bit_decoder)
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
        self._dynamic_table_size += len(name) + len(value) + 32
        while self._dynamic_table_size > self._dynamic_table_limit:
            old_name, old_value = self._dynamic_table.pop()
            self._dynamic_table_size -= len(old_name) + len(old_value) + 32

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
    return table

_static_table = _load_static_table()
