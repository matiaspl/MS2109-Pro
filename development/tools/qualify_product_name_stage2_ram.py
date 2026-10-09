"""Test the stage-2 MS2109-Pro candidate in volatile RAM; never write EEPROM."""
from __future__ import annotations
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_patch import validate
from ms2109_hid import Device

ART = ROOT / 'artifacts/ms2109-pro-name/20261007'
EXPECTED_EEPROM = '543d35dc33ff9f0bf60fe24066032c56aa40b23b7c2b58207c7afdb955f41961'
EXPECTED_CANDIDATE = 'b0b25243c155086bb0b96d41a5927104a3f04a8a1f5a3ae3930568943f5690d7'
OVERLAY_START = 0xCC00
OVERLAY_MAX = 2048 - 52


class EP0:
    def __init__(self):
        self.lib = C.CDLL('/opt/homebrew/lib/libusb-1.0.dylib')
        self.lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
        self.lib.libusb_init.restype = C.c_int
        self.lib.libusb_open_device_with_vid_pid.argtypes = [C.c_void_p, C.c_uint16, C.c_uint16]
        self.lib.libusb_open_device_with_vid_pid.restype = C.c_void_p
        self.lib.libusb_control_transfer.argtypes = [C.c_void_p, C.c_uint8, C.c_uint8,
            C.c_uint16, C.c_uint16, C.POINTER(C.c_ubyte), C.c_uint16, C.c_uint]
        self.lib.libusb_control_transfer.restype = C.c_int
        self.lib.libusb_reset_device.argtypes = [C.c_void_p]
        self.lib.libusb_reset_device.restype = C.c_int
        self.lib.libusb_close.argtypes = [C.c_void_p]
        self.lib.libusb_exit.argtypes = [C.c_void_p]
        self.ctx = C.c_void_p()
        rc = self.lib.libusb_init(C.byref(self.ctx))
        if rc:
            raise RuntimeError(f'libusb_init failed: {rc}')
        self.handle = self.lib.libusb_open_device_with_vid_pid(self.ctx, 0x534d, 0x2109)
        if not self.handle:
            self.close()
            raise RuntimeError('Could not open the enumerated MS2109 for raw EP0')

    def product(self):
        buf = (C.c_ubyte * 64)()
        n = self.lib.libusb_control_transfer(self.handle, 0x80, 6, 0x0302, 0x0409,
                                             buf, 64, 3000)
        if n < 0:
            raise RuntimeError(f'GET_DESCRIPTOR string 2 failed: {n}')
        raw = bytes(buf[:n])
        if len(raw) < 2 or raw[1] != 3 or raw[0] != len(raw):
            raise RuntimeError(f'Malformed product string descriptor: {raw.hex()}')
        return {'hex': raw.hex(), 'decoded': raw[2:].decode('utf-16le')}

    def reset_device(self):
        return self.lib.libusb_reset_device(self.handle)

    def close(self):
        if getattr(self, 'handle', None):
            self.lib.libusb_close(self.handle)
            self.handle = None
        if getattr(self, 'ctx', None):
            self.lib.libusb_exit(self.ctx)
            self.ctx = None


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_ram(device: Device, address: int, data: bytes):
    for offset, value in enumerate(data):
        device.exchange(0xB6, address + offset, value)


def run(output: Path):
    if output.exists():
        raise RuntimeError(f'Refusing to overwrite {output}')
    candidate_path = ART / 'ms2109-pro-calibrated-stereo-stage2.bin'
    candidate = candidate_path.read_bytes()
    candidate_hash = sha(candidate)
    code_length = validate(candidate)
    if candidate_hash != EXPECTED_CANDIDATE or len(candidate) != 2048:
        raise RuntimeError('Stage-2 candidate checksum/hash validation failed')
    output.parent.mkdir(parents=True, exist_ok=True)

    device = Device()
    ep0 = None
    snapshots = {}
    touched = False
    result = {'scope': 'volatile RAM qualification; EEPROM read-only',
              'candidate_sha256': candidate_hash, 'candidate_code_length': code_length,
              'checks': {}, 'restoration': {'attempted': False}}
    try:
        if device.identify_eeprom() != 2048:
            raise RuntimeError('Expected 2 KiB EEPROM')
        eeprom = device.read('eeprom', 0, 2048)
        result['eeprom_sha256_before'] = sha(eeprom)
        if result['eeprom_sha256_before'] != EXPECTED_EEPROM:
            raise RuntimeError('Live EEPROM does not match the currently installed candidate')
        live_n = validate(eeprom)
        spans = [(0xCBD0, 0x7FE), (0xC636, 24), (0xC2A4, 6), (0xC43B, 6),
                 (0xC4C5, 1), (0xC4C9, 3), (0xFE60, 1), (0xC6A0, 8), (0xFE90, 4)]
        for address, length in spans:
            snapshots[address] = device.read('ram', address, length)
        live = snapshots[0xCBD0]
        result['previous_flags'] = live[4]
        result['live_ram_code_length'] = int.from_bytes(live[2:4], 'big')
        result['loaded_image_matches_eeprom'] = (
            live[48:48 + live_n + 4] == eeprom[48:48 + live_n + 4])
        if not result['loaded_image_matches_eeprom']:
            raise RuntimeError('Loaded RAM overlay does not match the installed EEPROM image')
        result['before_product_ram_hex'] = snapshots[0xC636][:22].hex()
        ep0 = EP0()
        result['before_product_ep0'] = ep0.product()

        # Quiesce the callback while atomically replacing its RAM image.
        old_flags = result['previous_flags']
        device.exchange(0xB6, 0xCBD4, old_flags & ~0x01)
        time.sleep(0.03)
        if device.read('ram', 0xCBD4, 1) != bytes((old_flags & ~0x01,)):
            raise RuntimeError('Could not quiesce the common callback')
        touched = True
        header = bytearray(candidate[:48])
        header[4] = old_flags & ~0x01
        write_ram(device, 0xCBD0, bytes(header))
        write_ram(device, OVERLAY_START, candidate[48:48 + code_length + 4])
        if device.read('ram', 0xCBD0, 48) != bytes(header):
            raise RuntimeError('RAM header staging readback failed')
        if device.read('ram', OVERLAY_START, code_length + 4) != candidate[48:48 + code_length + 4]:
            raise RuntimeError('RAM overlay staging readback failed')
        device.exchange(0xB6, 0xCBD4, candidate[4])
        time.sleep(0.05)
        if device.read('ram', 0xCBD4, 1) != bytes((candidate[4],)):
            raise RuntimeError('Candidate callback did not enable')
        result['candidate_staged_in_ram'] = True

        # Stage 2 runs from the ROM polling loop after the boot descriptor builder.
        deadline = time.monotonic() + 5
        desired = bytes((22, 3)) + 'MS2109-Pro'.encode('utf-16le')
        while time.monotonic() < deadline:
            current = device.read('ram', 0xC636, len(desired))
            if current == desired:
                break
            time.sleep(0.1)
        result['product_ram_after_poll_hex'] = device.read('ram', 0xC636, len(desired)).hex()
        result['callback_stage2_repaired_buffer'] = (device.read('ram', 0xC636, len(desired)) == desired)
        result['product_ep0_before_usb_reset'] = ep0.product()
        reset_rc = ep0.reset_device()
        result['libusb_reset_device_result'] = reset_rc
        ep0.close()
        ep0 = None
        device.close()
        device = None
        if reset_rc:
            raise RuntimeError(f'USB bus reset failed: {reset_rc}')
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                device = Device()
                ep0 = EP0()
                break
            except Exception:
                if device is not None:
                    device.close()
                    device = None
                if ep0 is not None:
                    ep0.close()
                    ep0 = None
                time.sleep(0.5)
        if device is None or ep0 is None:
            raise RuntimeError('MS2109 did not re-enumerate after USB bus reset')
        result['live_header_after_usb_reset'] = device.read('ram', 0xCBD0, 16).hex()
        result['candidate_overlay_survived_usb_reset'] = (
            device.read('ram', OVERLAY_START, code_length + 4) ==
            candidate[48:48 + code_length + 4])
        result['product_ram_after_usb_reset_hex'] = device.read('ram', 0xC636, len(desired)).hex()
        result['product_ep0_after_usb_reset'] = ep0.product()
        result['ep0_matches_candidate'] = result['product_ep0_after_usb_reset']['decoded'] == 'MS2109-Pro'
        result['calibrated_procamp_retained'] = (
            device.read('ram', 0xC6A0, 8) == bytes.fromhex('eeff950000009300') and
            device.read('ram', 0xFE90, 4) == bytes.fromhex('ee959300'))
        result['color_records_retained'] = (
            device.read('ram', 0xC2A4, 6) == bytes.fromhex('06240d010101') and
            device.read('ram', 0xC43B, 6) == bytes.fromhex('06240d010101'))
        result['status'] = ('passed: stage-2 RAM hook returned MS2109-Pro over raw EP0' if
                            result['ep0_matches_candidate'] and result['calibrated_procamp_retained'] and
                            result['color_records_retained'] and result['candidate_overlay_survived_usb_reset'] else
                            'failed: stage-2 RAM candidate did not satisfy product/procamp checks')
    finally:
        if ep0 is not None:
            ep0.close()
        if touched:
            result['restoration']['attempted'] = True
            try:
                original_flags = snapshots[0xCBD0][4]
                device.exchange(0xB6, 0xCBD4, original_flags & ~0x01)
                time.sleep(0.03)
                for address, data in snapshots.items():
                    if address == 0xCBD0:
                        restored_header = bytearray(data)
                        restored_header[4] = original_flags & ~0x01
                        write_ram(device, address, bytes(restored_header))
                    else:
                        write_ram(device, address, data)
                device.exchange(0xB6, 0xCBD4, original_flags)
                result['restoration']['ram_ranges_match'] = all(
                    device.read('ram', address, len(data)) == data for address, data in snapshots.items())
                eeprom1 = device.read('eeprom', 0, 2048)
                eeprom2 = device.read('eeprom', 0, 2048)
                result['restoration']['eeprom_sha256_read1'] = sha(eeprom1)
                result['restoration']['eeprom_sha256_read2'] = sha(eeprom2)
                result['restoration']['eeprom_unchanged'] = (
                    eeprom1 == eeprom2 and sha(eeprom1) == EXPECTED_EEPROM)
                if not result['restoration']['ram_ranges_match'] or not result['restoration']['eeprom_unchanged']:
                    result['status'] = 'FAILED: restoration verification failed; power-cycle to reload EEPROM'
            except BaseException as error:
                result['restoration']['error'] = repr(error)
                result['status'] = 'FAILED: RAM restoration needs attention; power-cycle to reload EEPROM'
        if 'status' not in result:
            result['status'] = 'FAILED: qualification stopped before all checks completed'
        if device is not None:
            device.close()
        output.write_text(json.dumps(result, indent=2) + '\n')
        if result['status'].startswith('FAILED'):
            raise RuntimeError(result['status'])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))
