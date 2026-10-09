#!/usr/bin/env python3
"""Tests the capture analyzer's patch aggregation contract."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from analyze_color_capture import conversion_comparison, frame_values, metrics
from probe_colors import matrix


class CapturePatchAggregationTests(unittest.TestCase):
    def test_conversion_comparison_identifies_the_applied_range_model(self):
        expected = np.asarray([[0, 0, 0], [255, 255, 255], [255, 0, 0],
                               [0, 255, 0], [0, 0, 255], [127, 127, 127]], dtype=float)
        full, full_offset = matrix("709", "full")
        limited, limited_offset = matrix("709", "limited")
        yuv = expected @ full.T + full_offset
        observed = np.clip((yuv - limited_offset) @ np.linalg.inv(limited).T, 0, 255)

        comparison = conversion_comparison(yuv, observed, expected)

        self.assertEqual(comparison["709_limited"]["rmse_vs_avfoundation_bgra"], 0)
        best = min(comparison, key=lambda name: comparison[name]["rmse_vs_avfoundation_bgra"])
        self.assertEqual(best, "709_limited")

    def test_frame_pixels_reduce_to_one_median_per_chart_patch(self):
        patches = [
            {"rect": [0, 0, 32, 32]},
            {"rect": [32, 0, 32, 32]},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            frames = []
            for index in range(3):
                raw = np.zeros((360, 640, 4), dtype=np.uint8)
                values = [(50 + index, 60, 70), (180, 190 + index, 200)]
                for patch, rgb in zip(patches, values):
                    x, y, width, height = patch["rect"]
                    cx = round((x + width / 2) / 3)
                    cy = round((y + height / 2) / 3)
                    raw[cy - 1:cy + 1, cx - 1:cx + 1] = [rgb[2], rgb[1], rgb[0], 255]
                filename = f"frame-{index}.bgra"
                raw.tofile(directory / filename)
                frames.append({"file": filename, "bytes": raw.nbytes,
                               "pixel_format": "BGRA", "width": 640, "height": 360})

            result = frame_values(directory, {"patch_reference": patches, "frames": frames})

        self.assertEqual(result["median_values"].shape, (2, 3))
        np.testing.assert_array_equal(result["median_values"], [[51, 60, 70], [180, 191, 200]])
        np.testing.assert_array_equal(result["first_frame_values"], [[50, 60, 70], [180, 190, 200]])
        np.testing.assert_array_equal(result["after_first_median_values"], [[51.5, 60, 70], [180, 191.5, 200]])
        self.assertEqual(result["per_frame_patch_values"].shape, (3, 2, 3))
        np.testing.assert_array_equal(result["per_frame_patch_values"][0], [[50, 60, 70], [180, 190, 200]])
        self.assertEqual(result["maximum_temporal_patch_span"], 2)
        measured = metrics(result, np.asarray([[51, 60, 70], [180, 191, 200]], dtype=float))
        self.assertEqual(measured["rgb_rmse"], 0)


if __name__ == "__main__":
    unittest.main()
