import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from probe_procamp_setters import CONTROLS, next_value


class ProcampSetterProbeTests(unittest.TestCase):
    def test_controls_cover_standard_processing_unit_selectors(self):
        self.assertEqual({name: spec["selector"] for name, spec in CONTROLS.items()},
                         {"brightness": 2, "contrast": 3, "hue": 6, "saturation": 7})

    def test_candidate_moves_one_step_without_leaving_range(self):
        self.assertEqual(next_value(-18, -128, 127), -17)
        self.assertEqual(next_value(149, 0, 255), 150)
        self.assertEqual(next_value(127, -128, 127), 126)
        self.assertIsNone(next_value(2, 2, 2))


if __name__ == "__main__":
    unittest.main()
