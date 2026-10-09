"""Validate recovered rate semantics against execution of actual pinned ROM bytes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from audit_audio_rate_rom import execute

class AudioRateROMTests(unittest.TestCase):
    def test_distinct_byte_patterns_prove_width_and_order(self):
        result=execute(0x12345678,0x9abcdef0,0xa8,0x12)
        self.assertEqual(result['fe62_fe67'],'785634f0debc')
        self.assertEqual(result['c568_c56b'],'12345678')
        self.assertEqual(result['f809'],0x92)
        self.assertEqual(result['fe61'],0xa1)
        self.assertEqual([x[0] for x in result['writes']],
                         ['F809','FE62','FE63','FE64','FE65','FE66','FE67','FE61','FE61'])

    def test_all_fe61_initial_states_preserve_unrelated_bits(self):
        for before in range(256):
            with self.subTest(before=before):
                self.assertEqual(execute(48000,48000,before)['fe61'],before|8)
                self.assertEqual(execute(44100,48000,before)['fe61'],(before|1)&~8)

    def test_equal_low_24_bits_still_compare_full_32_bits(self):
        result=execute(0x0100bb80,0x0000bb80,0)
        self.assertEqual(result['fe62_fe67'],'80bb0080bb00')
        self.assertEqual(result['fe61'],1)

    def test_common_rate_bytes(self):
        for rate in (32000,44100,48000,88200,96000,176400,192000):
            with self.subTest(rate=rate):
                result=execute(rate,48000)
                self.assertEqual(bytes.fromhex(result['fe62_fe67']),
                                 rate.to_bytes(3,'little')+bytes.fromhex('80bb00'))

if __name__=='__main__': unittest.main()
