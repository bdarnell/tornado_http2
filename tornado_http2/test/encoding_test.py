import unittest

from tornado_http2.encoding import BitEncoder, BitDecoder, EODError

class BitEncoderTest(unittest.TestCase):
    def test_write_bit(self):
        encoder = BitEncoder()
        encoder.write_bit(1)
        self.assertEqual(encoder.data(), b'\x80')
        for b in [0, 1, 1, 0]:
            encoder.write_bit(b)
        self.assertEqual(encoder.data(), b'\xb0')
        for b in [1, 1, 1]:
            encoder.write_bit(b)
        # We have now written 8 bits; the first byte is full and the second
        # is not started.
        self.assertEqual(encoder.data(), b'\xb7')
        # Start the second byte.
        encoder.write_bit(0)
        self.assertEqual(encoder.data(), b'\xb7\x00')
        for i in range(7):
            encoder.write_bit(1)
        self.assertEqual(encoder.data(), b'\xb7\x7f')

class BitDecoderTest(unittest.TestCase):
    def test_read_bit(self):
        decoder = BitDecoder(bytearray(b'\xb7\x7f'))
        self.assertEqual(decoder.read_bit(), 1)
        # Finish the first byte.
        for b in [0, 1, 1, 0, 1, 1, 1]:
            self.assertEqual(decoder.read_bit(), b)
        # Read the second byte.
        for b in [0, 1, 1, 1, 1, 1, 1, 1]:
            self.assertEqual(decoder.read_bit(), b)
        with self.assertRaises(EODError):
            decoder.read_bit()
