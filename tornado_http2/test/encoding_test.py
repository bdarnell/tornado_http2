import unittest

from tornado_http2.encoding import BitEncoder, BitDecoder, EODError

class TestData(object):
    def __init__(self, *args):
        self.args = args

    def encode(self, encoder):
        for arg in self.args:
            self.encode_value(encoder, arg)

    def decode(self, test, decoder):
        for arg in self.args:
            test.assertEqual(self.decode_value(decoder), arg)

class Bits(TestData):
    def encode_value(self, encoder, arg):
        encoder.write_bit(arg)

    def decode_value(self, decoder):
        return decoder.read_bit()

class HpackInt(TestData):
    def encode_value(self, encoder, arg):
        encoder.write_hpack_int(arg)

    def decode_value(self, decoder):
        return decoder.read_hpack_int()

class HuffChar(TestData):
    def __init__(self, data):
        # convert strings to a sequence of bytes
        super(HuffChar, self).__init__(*list(data))

    def encode_value(self, encoder, arg):
        encoder.write_huffman_char(arg)

    def decode_value(self, decoder):
        return decoder.read_huffman_char(None)

test_data = [
    ('1-bit', [Bits(1)], [0b10000000], False),
    ('5-bits', [Bits(1, 0, 1, 1, 0)], [0b10110000], False),
    # 8 bits: the first byte is full and the second is not started.
    ('8-bits', [Bits(1, 0, 1, 1, 0, 1, 1, 1)], [0b10110111], True),
    ('9-bits', [Bits(1, 0, 1, 1, 0, 1, 1, 1, 0)],
     [0b10110111, 0b00000000], False),
    ('16-bits', [Bits(1, 0, 1, 1, 0, 1, 1, 1,
                      0, 1, 1, 1, 1, 1, 1, 1)],
     [0b10110111, 0b01111111], True),

    # Test cases from
    # http://tools.ietf.org/html/draft-ietf-httpbis-header-compression-12#appendix-C.1
    # Encode 10 with a 5-bit prefix.
    ('C.1.1', [Bits(1, 0, 1), HpackInt(10)], [0b10101010], True),
    # Encode 1337 with a 5-bit prefix.
    ('C.1.2', [Bits(0, 1, 0), HpackInt(1337)],
     [0b01011111, 0b10011010, 0b00001010], True),
    # Encode 42 on a byte boundary.
    ('C.1.3', [HpackInt(42)], [42], True),

    # Edge cases.
    # Rollover from 1 byte to 2.
    ('8-bit-prefix', [HpackInt(254)], [0b11111110], True),
    ('8-bit-prefix2', [HpackInt(255)], [0b11111111, 0b00000000], True),
    ('8-bit-prefix3', [HpackInt(256)], [0b11111111, 0b00000001], True),
    # A single bit followed by a 7-bit prefix.
    ('7-bit-prefix', [Bits(1), HpackInt(126)],
     [0b11111110], True),
    ('7-bit-prefix2', [Bits(1), HpackInt(127)],
     [0b11111111, 0b00000000], True),
    # Rollover from 2 bytes to 3.
    ('3-byte-rollover', [HpackInt(382)], [0b11111111, 0b01111111], True),
    ('3-byte-rollover2', [HpackInt(383)], [0b11111111, 0b10000000, 0b00000001],
     True),

    # Individual huffman-encoded characters
    ('huff1', [HuffChar(b'a')], [0b00011000], False),
    ('huff2', [HuffChar(b'Hi')], [0b11000110, 0b01100000], False),
    ]

class BitEncodingTest(unittest.TestCase):
    def test_bit_encoder(self):
        for name, calls, data, complete in test_data:
            try:
                encoder = BitEncoder()
                for c in calls:
                    c.encode(encoder)
                self.assertEqual(encoder.data(), bytearray(data))
            except Exception:
                print("Error in test case %s" % name)
                raise

    def test_bit_decoder(self):
        for name, calls, data, complete in test_data:
            try:
                decoder = BitDecoder(bytearray(data))
                for c in calls:
                    c.decode(self, decoder)
                if complete:
                    self.assertRaises(EODError, decoder.read_bit)
                else:
                    decoder.read_bit()
            except Exception:
                print("Error in test case %s" % name)
                print("Decoder offsets: %d, %d" % (
                    decoder._byte_offset, decoder._bit_offset))
                raise
