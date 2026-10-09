import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audio_ram_probe import Probe


class AudioRamProbeCodeTests(unittest.TestCase):
    def test_existing_probe_code_footprint_is_unchanged(self):
        self.assertEqual(len(Probe.build_code()), 148)

    def test_stream_start_reset_is_one_shot_and_fits_saved_ram_window(self):
        code = Probe.build_code(stream_start_reset=True)
        self.assertEqual(len(code), 199)
        self.assertLessEqual(len(code), 256)

        pop_offset = code.rfind(bytes.fromhex("d093"))
        monitor = code.find(bytes.fromhex("90de2b e0 60"))
        mailbox = code.find(bytes.fromhex("90de20 e0"))
        self.assertGreaterEqual(monitor, 0)
        self.assertLess(monitor, mailbox,
                        "stream monitor must run before the mailbox idle fast path")
        main_branch = code.find(bytes.fromhex("90de20 e0 70 03 02"))
        self.assertGreaterEqual(main_branch, 0)
        self.assertEqual(int.from_bytes(code[main_branch + 7:main_branch + 9], "big"),
                         0xD400 + pop_offset)

        armed_branch = code.find(bytes.fromhex("90de2b e0 60"))
        self.assertGreaterEqual(armed_branch, 0)
        self.assertEqual(armed_branch + 6 + code[armed_branch + 5], mailbox)

        alt_check = code.find(bytes.fromhex("e5 3a b4 01"))
        self.assertGreaterEqual(alt_check, 0)
        not_stream = alt_check + 5 + code[alt_check + 4]
        self.assertEqual(code[not_stream:not_stream + 3], bytes.fromhex("90de2a"))

        already_check = code.find(bytes.fromhex("90de2a e0 70"))
        self.assertGreaterEqual(already_check, 0)
        self.assertEqual(already_check + 6 + code[already_check + 5], mailbox)
        reset_jump = code.find(bytes.fromhex("759302 75800d 75800d 758005 80"))
        self.assertGreaterEqual(reset_jump, 0)
        self.assertEqual(reset_jump + 14 + code[reset_jump + 13], mailbox)

        self.assertIn(bytes.fromhex("759302 75800d 75800d 758005"), code)


if __name__ == "__main__":
    unittest.main()
