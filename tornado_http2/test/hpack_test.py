import binascii
import unittest

from tornado_http2.hpack import HpackDecoder

test_data = [
    # Test cases from
    # http://tools.ietf.org/html/draft-ietf-httpbis-header-compression-08#appendix-D.2
    ('D.2.1',
     [('400a 6375 7374 6f6d 2d6b 6579 0d63 7573'
       '746f 6d2d 6865 6164 6572',
       [(b'custom-key', b'custom-header')],
       55, [(b'custom-key', b'custom-header')]),
      ]),
    ('D.2.2',
     [('040c 2f73 616d 706c 652f 7061 7468',
       [(b':path', b'/sample/path')],
       0, []),
      ]),
    ('D.2.3',
     [('1008 7061 7373 776f 7264 0673 6563 7265'
       '74',
       [(b'password', b'secret')],
       0, []),
      ]),
    ('D.2.4',
     [('82',
       [(b':method', b'GET')],
       42, [(b':method', b'GET')]),
      ]),
    # TODO: add D.2.5 test (header table size limit)
    ('D.3',
     [('8287 8644 0f77 7777 2e65 7861 6d70 6c65'
       '2e63 6f6d',
       [(b':method', b'GET'),
        (b':scheme', b'http'),
        (b':path', b'/'),
        (b':authority', b'www.example.com')],
       180, [(b':authority', b'www.example.com'),
             (b':path', b'/'),
             (b':scheme', b'http'),
             (b':method', b'GET')]),
      ('5c08 6e6f 2d63 6163 6865',
       [(b'cache-control', b'no-cache'),
        (b':method', b'GET'),
        (b':scheme', b'http'),
        (b':path', b'/'),
        (b':authority', b'www.example.com')],
       233, [(b'cache-control', b'no-cache'),
             (b':authority', b'www.example.com'),
             (b':path', b'/'),
             (b':scheme', b'http'),
             (b':method', b'GET')]),
      ('3085 8c8b 8440 0a63 7573 746f 6d2d 6b65'
       '790c 6375 7374 6f6d 2d76 616c 7565',
       [(b':method', b'GET'),
        (b':scheme', b'https'),
        (b':path', b'/index.html'),
        (b':authority', b'www.example.com'),
        (b'custom-key', b'custom-value')],
       379, [(b'custom-key', b'custom-value'),
             (b':path', b'/index.html'),
             (b':scheme', b'https'),
             (b'cache-control', b'no-cache'),
             (b':authority', b'www.example.com'),
             (b':path', b'/'),
             (b':scheme', b'http'),
             (b':method', b'GET')]),
      ]),
    # D.4 encodes the same headers as D.3 but with huffman encoding.
    ('D.4',
     [('8287 8644 8cf1 e3c2 e5f2 3a6b a0ab 90f4'
       'ff',
       [(b':authority', b'www.example.com'),
        (b':method', b'GET'),
        (b':path', b'/'),
        (b':scheme', b'http')],
       180, [(b':authority', b'www.example.com'),
             (b':path', b'/'),
             (b':scheme', b'http'),
             (b':method', b'GET')]),
      ('5c86 a8eb 1064 9cbf',
       [(b':authority', b'www.example.com'),
        (b':method', b'GET'),
        (b':path', b'/'),
        (b':scheme', b'http'),
        (b'cache-control', b'no-cache')],
       233, [(b'cache-control', b'no-cache'),
             (b':authority', b'www.example.com'),
             (b':path', b'/'),
             (b':scheme', b'http'),
             (b':method', b'GET')]),
     ]),
]

def unhex_test_data(data):
    return bytearray(binascii.a2b_hex(''.join(data.split())))

class HpackDecoderTest(unittest.TestCase):
    def test_hpack_decoder(self):
        for name, requests in test_data:
            decoder = HpackDecoder()
            for i, (data, expected, expected_header_table_size,
                    expected_header_table) in enumerate(requests):
                try:
                    result = decoder.decode(unhex_test_data(data))
                    self.assertEqual(sorted(result), sorted(expected))
                    if expected_header_table_size is not None:
                        self.assertEqual(decoder._header_table_size,
                                         expected_header_table_size)
                    if expected_header_table is not None:
                        self.assertEqual(list(decoder._header_table),
                                         expected_header_table)
                except Exception:
                    print('error in test case %s, request %d' % (name, i))
                    raise
