"""Read-only cold-boot qualification for the calibrated MS2109 procamp defaults."""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_patch import validate
from ms2109_hid import Device

EXPECTED_RAM = {
    'C6A0': bytes.fromhex('eeff950000009400'),
    'FE90': bytes.fromhex('ee959400'),
}
EXPECTED_DEFAULTS = {2: -18, 3: 149, 6: 0, 7: 148}
CONTROL_NAMES = {2: 'brightness', 3: 'contrast', 6: 'hue', 7: 'saturation'}


class USB:
    def __init__(self):
        self.lib = C.CDLL('/opt/homebrew/lib/libusb-1.0.dylib')
        self.lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
        self.lib.libusb_init.restype = C.c_int
        self.lib.libusb_open_device_with_vid_pid.argtypes = [
            C.c_void_p, C.c_uint16, C.c_uint16]
        self.lib.libusb_open_device_with_vid_pid.restype = C.c_void_p
        self.lib.libusb_control_transfer.argtypes = [
            C.c_void_p, C.c_uint8, C.c_uint8, C.c_uint16, C.c_uint16,
            C.POINTER(C.c_ubyte), C.c_uint16, C.c_uint]
        self.lib.libusb_control_transfer.restype = C.c_int
        self.lib.libusb_close.argtypes = [C.c_void_p]
        self.lib.libusb_exit.argtypes = [C.c_void_p]
        self.ctx = C.c_void_p()
        rc = self.lib.libusb_init(C.byref(self.ctx))
        if rc:
            raise RuntimeError(f'libusb_init failed: {rc}')
        self.handle = self.lib.libusb_open_device_with_vid_pid(
            self.ctx, 0x534D, 0x2109)
        if not self.handle:
            self.close()
            raise RuntimeError('MS2109 is not enumerated after reconnect')

    def control(self, bm, request, value, index, length):
        buf = (C.c_ubyte * max(1, length))()
        rc = self.lib.libusb_control_transfer(
            self.handle, bm, request, value, index, buf, length, 3000)
        return int(rc), bytes(buf[:max(0, rc)])

    def get_control(self, selector, request):
        return self.control(0xA1, request, selector << 8, 0x0200, 2)

    def string(self, index):
        rc, data = self.control(0x80, 6, 0x0300 | index, 0x0409, 64)
        if rc < 0 or len(data) < 2 or data[0] != len(data) or data[1] != 3:
            raise RuntimeError(f'USB string {index} is malformed: rc={rc}, data={data.hex()}')
        return data[2:].decode('utf-16le')

    def close(self):
        if getattr(self, 'handle', None):
            self.lib.libusb_close(self.handle)
            self.handle = None
        if getattr(self, 'ctx', None):
            self.lib.libusb_exit(self.ctx)
            self.ctx = None


def signed_value(selector, data):
    return int.from_bytes(data, 'little', signed=selector in (2, 6))


def run(output: Path, candidate: Path, expected_sha256: str | None = None):
    if output.exists():
        raise RuntimeError(f'Refusing to overwrite {output}')
    image = candidate.read_bytes()
    validate(image)
    candidate_sha256 = hashlib.sha256(image).hexdigest()
    if expected_sha256 and candidate_sha256 != expected_sha256:
        raise RuntimeError('Candidate hash does not match the installed image under review')

    result = {
        'scope': 'read-only procamp defaults cold-boot qualification',
        'candidate_sha256_expected': expected_sha256 or candidate_sha256,
        'controls': {},
        'writes_performed': 0,
    }
    device = Device()
    try:
        size = device.identify_eeprom()
        eeprom_a = device.read('eeprom', 0, size)
        eeprom_b = device.read('eeprom', 0, size)
        result['eeprom_sha256_reads'] = [
            hashlib.sha256(eeprom_a).hexdigest(),
            hashlib.sha256(eeprom_b).hexdigest()]
        result['eeprom_reads_match'] = eeprom_a == eeprom_b
        result['eeprom_matches_candidate'] = eeprom_a == image
        result['eeprom_code_bytes'] = validate(eeprom_a)
        code_bytes = result['eeprom_code_bytes']
        ram_header = device.read('ram', 0xCBD0, 48)
        loaded_overlay = device.read('ram', 0xCC00, code_bytes + 4)
        result['loaded_firmware'] = {
            'ram_header_matches_candidate': ram_header == image[:48],
            'overlay_sha256': hashlib.sha256(loaded_overlay).hexdigest(),
            'overlay_matches_candidate': (
                loaded_overlay == image[48:48 + code_bytes + 4]),
        }
        result['startup_ram'] = {
            'C6A0': device.read('ram', 0xC6A0, 8).hex(),
            'FE90': device.read('ram', 0xFE90, 4).hex(),
        }
        result['startup_ram_matches'] = all(
            bytes.fromhex(result['startup_ram'][address]) == data
            for address, data in EXPECTED_RAM.items())
    finally:
        device.close()

    usb = USB()
    try:
        for selector, expected in EXPECTED_DEFAULTS.items():
            get_def_rc, get_def = usb.get_control(selector, 0x87)
            get_cur_rc, get_cur = usb.get_control(selector, 0x81)
            get_def_value = signed_value(selector, get_def) if len(get_def) == 2 else None
            get_cur_value = signed_value(selector, get_cur) if len(get_cur) == 2 else None
            result['controls'][CONTROL_NAMES[selector]] = {
                'selector': selector,
                'get_def_return_code': get_def_rc,
                'get_def_hex': get_def.hex(),
                'get_def_value': get_def_value,
                'get_def_matches': get_def_rc == 2 and get_def_value == expected,
                'get_cur_return_code': get_cur_rc,
                'get_cur_hex': get_cur.hex(),
                'get_cur_value': get_cur_value,
                'get_cur_matches_startup': get_cur_rc == 2 and get_cur_value == expected,
            }
        result['usb_strings'] = {
            '2': usb.string(2),
            '4': usb.string(4),
        }
        result['usb_names_match'] = all(
            name == 'MS2109-Pro' for name in result['usb_strings'].values())
    finally:
        usb.close()

    passed = (result['eeprom_reads_match'] and
              result['eeprom_matches_candidate'] and
              result['loaded_firmware']['ram_header_matches_candidate'] and
              result['loaded_firmware']['overlay_matches_candidate'] and
              result['startup_ram_matches'] and
              result['usb_names_match'] and
              all(item['get_def_matches'] for item in result['controls'].values()))
    result['status'] = 'passed' if passed else 'failed: one or more cold-boot checks mismatched'
    result['note'] = ('GET_CUR is recorded but is not a pass gate because the USB host '
                      'may apply its own current-value policy after enumeration.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.candidate, args.expected_sha256), indent=2))
