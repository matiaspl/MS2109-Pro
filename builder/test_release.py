import hashlib
import json
import unittest
from pathlib import Path

from build_release import EXPECTED_SHA256, ROOT, build_release
from release_builder import validate


class ReleaseBuildTests(unittest.TestCase):
    def test_rebuild_matches_installed_firmware(self):
        image, overlay, _ = build_release()
        installed = (ROOT / "firmware/ms2109-pro.bin").read_bytes()
        self.assertEqual(image, installed)
        self.assertEqual(hashlib.sha256(image).hexdigest(), EXPECTED_SHA256)
        self.assertEqual(len(image), 2048)
        self.assertLessEqual(validate(image), 1996)
        self.assertEqual(len(overlay), 1851)

    def test_release_manifest_records_cold_start_mode_table(self):
        manifest = json.loads((ROOT / "firmware/ms2109-pro.json").read_text())
        self.assertEqual(manifest["uvc_controls"], "stock mask-ROM descriptor and request handling")
        self.assertEqual(manifest["usb_header_names"], {"video": "usb video", "audio": "usb video"})
        self.assertEqual(manifest["cold_restart_descriptor"]["fps_approx"], [30, 30, 25, 20, 10])
        self.assertEqual(manifest["cold_restart_descriptor"]["default_interval_100ns"], 333333)


if __name__ == "__main__":
    unittest.main()
