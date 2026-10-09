"""Run the same emitted-code acceptance tests with the ROM-only EDID layout."""
import unittest
from unittest.mock import patch
from tests import test_sharpness_firmware as firmware
from sharpness_firmware import assemble

VARIANT = assemble(firmware.ORIGINAL, firmware.ROM, edid_source='rom')


class RomEdidSharpnessTests(firmware.SharpnessFirmwareTests):
    def setUp(self):
        replacement = patch.object(firmware, 'PROTOTYPE', VARIANT)
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_rom_edid_modes_audio_and_size_saving(self):
        baseline = assemble(firmware.ORIGINAL, firmware.ROM)
        self.assertEqual(baseline.report['overlay_sha256'],
                         '5dcbad120daac1e56272d814d3669dbf41b7ec6ecb53e8735d08f24a49c684f0')
        self.assertEqual(len(baseline.overlay)-len(VARIANT.overlay), 158)
        self.assertEqual(VARIANT.report['deficit_bytes'], 284)
        self.assertIsNone(VARIANT.report['memory']['edid_buffer'])
        edid = firmware.ROM[0x7738:0x7838]
        self.assertEqual([sum(edid[i:i+128]) % 256 for i in (0, 128)], [0, 0])
        dtd = edid[54:72]
        self.assertEqual(int.from_bytes(dtd[:2], 'little')*10000, 148500000)
        self.assertEqual(dtd[2]+((dtd[4] >> 4) << 8), 1920)
        self.assertEqual(dtd[5]+((dtd[7] >> 4) << 8), 1080)
        def blocks(data):
            ext, result = data[128:], {}
            pos = 4
            while pos < ext[2]:
                tag, count = ext[pos] >> 5, ext[pos] & 31
                result[tag] = bytes(ext[pos+1:pos+1+count])
                pos += count+1
            return result
        default = blocks(edid)
        custom = blocks(firmware.ORIGINAL[48+0x152:48+0x252])
        self.assertEqual(default[1], custom[1])  # Identical audio descriptors.
        self.assertTrue({4, 16}.issubset({value & 127 for value in default[2]}))


if __name__ == '__main__':
    unittest.main()
