"""Read-only live snapshots around MS2109 procamp UVC GET_DEF requests."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_patch import validate
from ms2109_hid import Device
from qualify_procamp_defaults_cold_boot import USB

CANDIDATE_SHA256 = '91f4d30b5a85a2cca368b84ec1f1437ee30af29bc002fca9073993513a71ba3f'
CANDIDATE = ROOT / 'artifacts/sharpness-firmware/20261008-procamp-defaults/ms2109-procamp-defaults-v3-ms2109-pro-candidate.bin'
SELECTORS = {2: 'brightness', 3: 'contrast', 6: 'hue', 7: 'saturation'}
SNAPSHOTS = {
    'setup_length_C000': (0xC000, 2),
    'ep0_offset_C008': (0xC008, 5),
    'response_buffer_C020': (0xC020, 2),
    'rom_source_pointer_C5F9': (0xC5F9, 3),
}


def snapshot():
    device = Device()
    try:
        return {name: device.read('ram', address, size).hex()
                for name, (address, size) in SNAPSHOTS.items()}
    finally:
        device.close()


def run(output: Path):
    if output.exists():
        raise RuntimeError(f'Refusing to overwrite {output}')
    candidate = CANDIDATE.read_bytes()
    validate(candidate)
    if hashlib.sha256(candidate).hexdigest() != CANDIDATE_SHA256:
        raise RuntimeError('Saved v3 candidate digest changed')

    device = Device()
    try:
        size = device.identify_eeprom()
        first = device.read('eeprom', 0, size)
        second = device.read('eeprom', 0, size)
        eeprom_hashes = [hashlib.sha256(first).hexdigest(),
                         hashlib.sha256(second).hexdigest()]
        if first != second or first != candidate:
            raise RuntimeError('Connected EEPROM is not the exact verified v3 image')
    finally:
        device.close()

    usb = USB()
    try:
        trace = []
        for selector, name in SELECTORS.items():
            usb.close()
            before = snapshot()
            usb = USB()
            rc, data = usb.get_control(selector, 0x87)
            usb.close()
            after = snapshot()
            trace.append({
                'control': name,
                'selector': selector,
                'bmRequestType': '0xA1',
                'bRequest': '0x87',
                'wValue': f'0x{selector << 8:04X}',
                'wIndex': '0x0200',
                'wLength': 2,
                'transfer_return_code': rc,
                'response_hex': data.hex(),
                'before': before,
                'after': after,
            })
        result = {
            'scope': 'read-only live GET_DEF dispatch/EP0 buffer trace',
            'candidate_sha256': CANDIDATE_SHA256,
            'eeprom_sha256_reads': eeprom_hashes,
            'eeprom_matches_candidate': True,
            'writes_performed': 0,
            'snapshots': {name: {'address': f'0x{address:04X}', 'length': size}
                          for name, (address, size) in SNAPSHOTS.items()},
            'requests': trace,
        }
    finally:
        usb.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))
