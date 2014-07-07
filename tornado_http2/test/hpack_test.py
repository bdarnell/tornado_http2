import binascii
import unittest

from tornado_http2.hpack import HpackDecoder

test_data = [
    # Test cases from
    # http://tools.ietf.org/html/draft-ietf-httpbis-header-compression-08#appendix-D.2
    ('D.2.1',
     '400a 6375 7374 6f6d 2d6b 6579 0d63 7573'
     '746f 6d2d 6865 6164 6572',
     [(b'custom-key', b'custom-header')],
     55, [(b'custom-key', b'custom-header')]),
    ('D.2.2',
     '040c 2f73 616d 706c 652f 7061 7468',
     [(b':path', b'/sample/path')],
     0, []),
    ('D.2.3',
     '1008 7061 7373 776f 7264 0673 6563 7265'
     '74',
     [(b'password', b'secret')],
     0, []),
    ('D.2.4',
     '82',
     [(b':method', b'GET')],
     42, [(b':method', b'GET')]),
    # TODO: add D.2.5 test (header table size limit)
]

def unhex_test_data(data):
    return bytearray(binascii.a2b_hex(''.join(data.split())))

class HpackDecoderTest(unittest.TestCase):
    def test_hpack_decoder(self):
        for (name, data, expected, expected_header_table_size,
             expected_header_table) in test_data:
            try:
                decoder = HpackDecoder()
                result = decoder.decode(unhex_test_data(data))
                self.assertEqual(result, expected)
                if expected_header_table_size is not None:
                    self.assertEqual(decoder._header_table_size,
                                     expected_header_table_size)
                if expected_header_table is not None:
                    self.assertEqual(decoder._header_table[1:],
                                     expected_header_table)
            except Exception:
                print('error in test case', name)
                raise
