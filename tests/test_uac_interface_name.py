import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_patch import validate
from mcs51_rom_harness import CPU
from patch_uac_interface_name import (
    BASELINE, HELPER, HELPER_ADDRESS, CALL_SITE, CALL_STUB, build,
)

ROM = (ROOT / "backups/ms2109-maskrom.bin").read_bytes()
SOURCE = BASELINE.read_bytes()


def get_configuration(cpu, kind, source):
    pointer = 0xC03A
    if kind == 2:
        cpu.xdata[pointer:pointer + len(source)] = source
    cpu.xdata[0xC002:0xC004] = pointer.to_bytes(2, "big")
    length = len(source)
    cpu.iram[0x0B:0x13] = bytes((
        0x80, 6, kind, 0, 0, 0, (length >> 8) & 255, length & 255))
    cpu.xdata[0xC000:0xC002] = length.to_bytes(2, "big")
    cpu.output.clear()
    cpu.put(0x80, 0)
    cpu.run(0xCC10, return_to=0x4792)
    response = bytearray(cpu.output)
    for _ in range(32):
        if not any(cpu.iram[8:10]):
            break
        cpu.output.clear()
        cpu.put(0x80, 0)
        cpu.run(0xCC10, return_to=0x4792)
        response.extend(cpu.output)
    else:
        raise AssertionError("configuration descriptor transfer did not terminate")
    return bytes(response)


class UacInterfaceNameTests(unittest.TestCase):
    def test_candidate_rewrites_only_known_interface_string_indexes(self):
        candidate, metadata = build(SOURCE)
        self.assertEqual(validate(candidate), 1950)
        self.assertEqual(metadata["uac_interface_string"], "MS2109-Pro")
        self.assertEqual(metadata["uac_interface_string_index"], 2)
        self.assertEqual(metadata["eeprom_writes"], 0)
        self.assertIn("active type-2 ROM path", metadata["status"])
        self.assertIn("processing bitmap 1F00", metadata["live_probe"]["type_2"])
        self.assertIn("type-2 ROM response", metadata["sharpness_advertisement"])
        self.assertIn("1F00", metadata["sharpness_advertisement"])
        self.assertEqual(HELPER_ADDRESS, 0xD370)
        self.assertEqual(CALL_SITE, 0xCDAB)
        self.assertEqual(CALL_STUB[:1], b"\x12")
        self.assertEqual(len(HELPER), 46)

        for kind, source, offsets in (
            (2, ROM[0x7111:0x75CC], (0x447, 0x476, 0x47F)),
            (7, ROM[0x75CC:0x772F], (0x0EF, 0x11E, 0x127)),
        ):
            with self.subTest(descriptor_type=kind):
                cpu = CPU(ROM, candidate[48:48 + validate(candidate)])
                actual = get_configuration(cpu, kind, source)
                expected = bytearray(source)
                for offset in offsets:
                    self.assertEqual(expected[offset], 4)
                    expected[offset] = 2
                self.assertEqual(actual, bytes(expected))
                self.assertEqual(actual[0x41:0x43], b"\x0f\x00")

    def test_candidate_preserves_baseline_and_passes_container_checks(self):
        before = hashlib.sha256(SOURCE).hexdigest()
        candidate, _ = build(SOURCE)
        self.assertEqual(hashlib.sha256(SOURCE).hexdigest(), before)
        self.assertEqual(validate(candidate), int.from_bytes(candidate[2:4], "big"))
        self.assertEqual(candidate[:2], SOURCE[:2])
        self.assertEqual(candidate[4:48], SOURCE[4:48])

    def test_builder_rejects_a_different_or_modified_eeprom(self):
        with self.assertRaises(ValueError):
            build(SOURCE[:-1])
        changed = bytearray(SOURCE)
        changed[100] ^= 1
        with self.assertRaises(ValueError):
            build(bytes(changed))


if __name__ == "__main__":
    unittest.main()
