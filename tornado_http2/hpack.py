import os
from tornado.escape import utf8

from .encoding import BitDecoder

class HpackDecoder(object):
    def __init__(self):
        # Dummy entry 0 in header_table
        self._header_table = [None]
        self._header_table_size = 0

    def decode(self, data):
        header_set = []
        bit_decoder = BitDecoder(data)
        while not bit_decoder.eod():
            is_indexed = bit_decoder.read_bit()
            if is_indexed:
                idx = bit_decoder.read_hpack_int()
                name, value = _static_table[idx]
                header_set.append((name, value))
                self.add_to_header_table(name, value)
            else:
                add_to_index = bit_decoder.read_bit()
                if add_to_index:
                    name, value = self.read_name_value_pair(bit_decoder)
                    header_set.append((name, value))
                    self.add_to_header_table(name, value)
                else:
                    is_context_update = bit_decoder.read_bit()
                    if is_context_update:
                        raise NotImplementedError()
                    else:
                        # read the never-index bit and discard for now.
                        bit_decoder.read_bit()
                        header_set.append(self.read_name_value_pair(bit_decoder))
        return header_set

    def read_name_value_pair(self, bit_decoder):
        name_index = bit_decoder.read_hpack_int()
        if name_index == 0:
            name = self.read_string(bit_decoder)
        else:
            name = _static_table[name_index][0]
        value = self.read_string(bit_decoder)
        return name, value

    def read_string(self, bit_decoder):
        is_huffman = bit_decoder.read_bit()
        length = bit_decoder.read_hpack_int()
        if is_huffman:
            read_char = bit_decoder.read_huffman_char
        else:
            read_char = bit_decoder.read_char
        return bytes(bytearray([read_char() for i in range(length)]))

    def add_to_header_table(self, name, value):
        self._header_table.append((name, value))
        self._header_table_size += len(name) + len(value) + 32

def _load_static_table():
    """Parses the hpack static table, which was copied from
    http://http2.github.io/http2-spec/compression.html#static.table
    corresponding to
    http://tools.ietf.org/html/draft-ietf-httpbis-header-compression-08#appendix-B
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
