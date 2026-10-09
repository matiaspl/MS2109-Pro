import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from audit_sharpness_candidate_space import (  # noqa: E402
    audit,
    decode_delta,
    encode_delta,
)


class SharpnessSpaceTests(unittest.TestCase):
    def test_compact_delta_reconstructs_custom_edid_exactly(self):
        original = (ROOT / "backups/ms2109-original.bin").read_bytes()
        rom = (ROOT / "backups/ms2109-maskrom.bin").read_bytes()
        custom = original[0x30 + 0x152:0x30 + 0x152 + 256]
        default = rom[0x7738:0x7738 + 256]

        encoded = encode_delta(default, custom)

        self.assertEqual(len(encoded), 124)
        self.assertEqual(encoded[0], 11)
        self.assertEqual(decode_delta(default, encoded), custom)

    def test_audit_reports_reproducible_code_budget(self):
        result = audit()
        self.assertEqual(result["qualified_calibrated_stereo_code_bytes"], 1950)
        self.assertEqual(result["qualified_calibrated_stereo_free_bytes"], 46)
        self.assertTrue(result["custom_edid"]["reconstruction_exact"])
        self.assertEqual(
            result["hypothetical_after_table_replacement"][
                "remaining_bytes_before_decoder_and_features"
            ],
            178,
        )


if __name__ == "__main__":
    unittest.main()
