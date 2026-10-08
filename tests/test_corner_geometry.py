import json
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_corner_geometry import analyze_luma
from capture_corner_geometry import analyze_capture
from generate_corner_geometry_chart import make_chart


class CornerGeometryTests(unittest.TestCase):
    def test_identifies_all_corners_and_reports_translation_overflow(self):
        image, manifest = make_chart(1280, 720)
        source = np.asarray(image.convert("L"), dtype=np.uint8)
        baseline = analyze_luma(source, manifest)
        json.dumps(baseline)
        self.assertTrue(baseline["all_corner_markers_found"], baseline["markers"])
        self.assertTrue(baseline["viewport_fit"]["within_viewport"])

        shifted = np.full_like(source, 128)
        shifted[4:, 6:] = source[:-4, :-6]
        moved = analyze_luma(shifted, manifest)
        json.dumps(moved)
        self.assertTrue(moved["all_corner_markers_found"], moved["markers"])
        self.assertAlmostEqual(moved["viewport_fit"]["horizontal_offset_px"], 6, delta=1)
        self.assertAlmostEqual(moved["viewport_fit"]["vertical_offset_px"], 4, delta=1)
        self.assertGreater(moved["viewport_fit"]["overflow_px"]["right_px"], 4)
        self.assertFalse(moved["viewport_fit"]["within_viewport"])

    def test_capture_geometry_checks_every_frame_and_serializes(self):
        image, manifest = make_chart(1280, 720)
        luma = np.asarray(image.convert("L"), dtype=np.uint8)
        packed = np.zeros((3, 720, 1280, 2), dtype=np.uint8)
        packed[:, :, :, 0] = luma
        packed[:, :, :, 1] = 128
        first, identical, geometries = analyze_capture(
            packed.tobytes(), 1280, 720, 3, manifest)
        self.assertTrue(identical)
        self.assertEqual(len(geometries), 3)
        self.assertTrue(first["all_corner_markers_found"])
        self.assertTrue(all(item["viewport_fit"]["within_viewport"]
                            for item in geometries))
        json.dumps(geometries)


if __name__ == "__main__":
    unittest.main()
