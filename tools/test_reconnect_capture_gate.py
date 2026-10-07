#!/usr/bin/env python3
"""Protect the no-write, immediate-frame reconnect qualification gate."""
import json
import tempfile
import unittest
from pathlib import Path

from qualify_reconnect_cycles import valid_format


class ReconnectCaptureGateTests(unittest.TestCase):
    def test_accepts_eight_immediate_get_cur_only_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            metadata = {
                "exit_code": 0,
                "frames_captured": 8,
                "frames_skipped_for_settling": 0,
                "getter_profile": "GET_CUR only",
                "control_profile": "untouched",
                "controls_restoration_ok": True,
            }
            (directory / "usb-capture.json").write_text(json.dumps(metadata))
            (directory / "control-requests.jsonl").write_text(
                '{"direction":"IN","bRequest":129}\n')
            (directory.parent / f"{directory.name}-display-ready.json").write_text(json.dumps({
                "target_display_available": True,
                "display_profile_matches": True,
                "window_screen": "HDMI TO USB",
                "display_generation": 0,
            }))
            self.assertTrue(valid_format(directory))

    def test_rejects_control_writes_or_settling_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            metadata = {
                "exit_code": 0,
                "frames_captured": 8,
                "frames_skipped_for_settling": 0,
                "getter_profile": "GET_CUR only",
                "control_profile": "untouched",
                "controls_restoration_ok": True,
            }
            (directory / "usb-capture.json").write_text(json.dumps(metadata))
            requests = directory / "control-requests.jsonl"
            (directory.parent / f"{directory.name}-display-ready.json").write_text(json.dumps({
                "target_display_available": True,
                "display_profile_matches": True,
                "window_screen": "HDMI TO USB",
                "display_generation": 0,
            }))
            requests.write_text('{"direction":"OUT","bRequest":1}\n')
            self.assertFalse(valid_format(directory))
            requests.write_text('{"direction":"IN","bRequest":129}\n')
            metadata["frames_skipped_for_settling"] = 1
            (directory / "usb-capture.json").write_text(json.dumps(metadata))
            self.assertFalse(valid_format(directory))
            metadata["frames_skipped_for_settling"] = 0
            (directory / "usb-capture.json").write_text(json.dumps(metadata))
            (directory.parent / f"{directory.name}-display-ready.json").write_text(json.dumps({
                "target_display_available": True,
                "display_profile_matches": False,
                "window_screen": "HDMI TO USB",
                "display_generation": 1,
            }))
            self.assertFalse(valid_format(directory))


if __name__ == "__main__":
    unittest.main()
