import binascii
import unittest

from tornado_http2.hpack import HpackDecoder

test_data = [
    # Test cases from
    # http://tools.ietf.org/html/draft-ietf-httpbis-header-compression-12#appendix-C.2
    ('C.2.1',
     [('400a 6375 7374 6f6d 2d6b 6579 0d63 7573'
       '746f 6d2d 6865 6164 6572',
       [(b'custom-key', b'custom-header')],
       55, [(b'custom-key', b'custom-header')]),
      ]),
    ('C.2.2',
     [('040c 2f73 616d 706c 652f 7061 7468',
       [(b':path', b'/sample/path')],
       0, []),
      ]),
    ('C.2.3',
     [('1008 7061 7373 776f 7264 0673 6563 7265'
       '74',
       [(b'password', b'secret')],
       0, []),
      ]),
    ('C.2.4',
     [('82',
       [(b':method', b'GET')],
       0, []),
      ]),
    ('C.3',
     [('8286 8441 0f77 7777 2e65 7861 6d70 6c65'
       '2e63 6f6d',
       [(b':method', b'GET'),
        (b':scheme', b'http'),
        (b':path', b'/'),
        (b':authority', b'www.example.com')],
       57, [(b':authority', b'www.example.com')]),
      ('8286 84be 5808 6e6f 2d63 6163 6865',
       [(b':method', b'GET'),
        (b':scheme', b'http'),
        (b':path', b'/'),
        (b':authority', b'www.example.com'),
        (b'cache-control', b'no-cache')],
       110, [(b'cache-control', b'no-cache'),
             (b':authority', b'www.example.com')]),
      ('8287 85bf 400a 6375 7374 6f6d 2d6b 6579'
       '0c63 7573 746f 6d2d 7661 6c75 65',
       [(b':method', b'GET'),
        (b':scheme', b'https'),
        (b':path', b'/index.html'),
        (b':authority', b'www.example.com'),
        (b'custom-key', b'custom-value')],
       164, [(b'custom-key', b'custom-value'),
             (b'cache-control', b'no-cache'),
             (b':authority', b'www.example.com')]),
      ]),
    # C.4 encodes the same headers as C.3 but with huffman encoding.
    ('C.4',
     [('8286 8441 8cf1 e3c2 e5f2 3a6b a0ab 90f4'
       'ff',
       [(b':method', b'GET'),
        (b':scheme', b'http'),
        (b':path', b'/'),
        (b':authority', b'www.example.com')],
       57, [(b':authority', b'www.example.com')]),
      ('8286 84be 5886 a8eb 1064 9cbf',
       [(b':method', b'GET'),
        (b':scheme', b'http'),
        (b':path', b'/'),
        (b':authority', b'www.example.com'),
        (b'cache-control', b'no-cache')],
       110, [(b'cache-control', b'no-cache'),
             (b':authority', b'www.example.com')]),
      # ('8287 85bf 4088 25a8 49e9 5ba9 7d7f 8925'
      #   'a849 e95b b8e8 b4bf',
      #  [(b':method', b'GET'),
      #   (b':scheme', b'https'),
      #   (b':path', b'/index.html'),
      #   (b':authority', b'www.example.com'),
      #   (b'custom-key', b'custom-value')],
      #  164, [(b'custom-key', b'custom-value'),
      #        (b'cache-control', b'no-cache'),
      #        (b':authority', b'www.example.com')]),
     ]),
]

def unhex_test_data(data):
    return bytearray(binascii.a2b_hex(''.join(data.split())))

class HpackDecoderTest(unittest.TestCase):
    def test_hpack_decoder(self):
        for name, requests in test_data:
            decoder = HpackDecoder()
            for i, (data, expected, expected_dynamic_table_size,
                    expected_dynamic_table) in enumerate(requests):
                try:
                    result = decoder.decode(unhex_test_data(data))
                    self.assertEqual(result, expected)
                    if expected_dynamic_table_size is not None:
                        self.assertEqual(decoder._dynamic_table_size,
                                         expected_dynamic_table_size)
                    if expected_dynamic_table is not None:
                        self.assertEqual(list(decoder._dynamic_table),
                                         expected_dynamic_table)
                except Exception:
                    print('error in test case %s, request %d' % (name, i))
                    raise
