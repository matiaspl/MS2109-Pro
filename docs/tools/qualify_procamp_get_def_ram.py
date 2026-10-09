"""Qualify the GET_DEF EP0 fix in RAM, then restore the installed image exactly."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_patch import validate
from ms2109_hid import Device
from qualify_procamp_defaults_cold_boot import USB, EXPECTED_DEFAULTS, signed_value

ART = ROOT / 'artifacts/sharpness-firmware/20261008-procamp-defaults'
CURRENT = ART / 'ms2109-procamp-defaults-v3-ms2109-pro-candidate.bin'
CANDIDATE = ART / 'ms2109-procamp-defaults-v4-ms2109-pro-candidate.bin'
RUNNING_V1 = ART / 'ms2109-procamp-defaults-ms2109-pro-candidate.bin'
CURRENT_SHA256 = '91f4d30b5a85a2cca368b84ec1f1437ee30af29bc002fca9073993513a71ba3f'
CANDIDATE_SHA256 = 'a42bfa5919cf164a2a1b4edb4152b156fe65db5c58e55da9d53ef1c0bb52a3eb'
RUNNING_V1_SHA256 = '8fbbc47c8fc9064d3d781d5fa65e11d9bb62fa3f7a491f1f5be14531df54da9d'
OVERLAY_START = 0xCC00
HEADER_START = 0xCBD0
HOOK_MASK = 0x07  # common, USB setup, and IRQ callbacks in this image


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_ram(device: Device, address: int, data: bytes) -> None:
    for offset, value in enumerate(data):
        device.exchange(0xB6, address + offset, value)


def read_defaults(usb: USB) -> dict:
    output = {}
    for selector, expected in EXPECTED_DEFAULTS.items():
        rc, data = usb.get_control(selector, 0x87)
        output[str(selector)] = {
            'return_code': rc,
            'hex': data.hex(),
            'value': signed_value(selector, data) if len(data) == 2 else None,
            'matches': rc == 2 and len(data) == 2 and
                       signed_value(selector, data) == expected,
        }
    return output


def run(output: Path) -> dict:
    if output.exists():
        raise RuntimeError(f'Refusing to overwrite {output}')
    current = CURRENT.read_bytes()
    candidate = CANDIDATE.read_bytes()
    running_v1 = RUNNING_V1.read_bytes()
    current_length = validate(current)
    candidate_length = validate(candidate)
    running_v1_length = validate(running_v1)
    if (sha(current) != CURRENT_SHA256 or sha(candidate) != CANDIDATE_SHA256 or
            sha(running_v1) != RUNNING_V1_SHA256):
        raise RuntimeError('Saved v1/v3/v4 candidate hash changed')

    result = {
        'scope': 'volatile RAM-only live GET_DEF qualification with exact restoration',
        'current_eeprom_expected_sha256': CURRENT_SHA256,
        'candidate_sha256': CANDIDATE_SHA256,
        'current_code_bytes': current_length,
        'candidate_code_bytes': candidate_length,
        'eeprom_writes': 0,
        'checks': {},
        'restoration': {'attempted': False},
    }
    device = Device()
    usb = None
    original_header = None
    original_overlay = None
    restore_length = max(current_length, candidate_length) + 4
    touched = False
    operation_error = None
    try:
        if device.identify_eeprom() != 2048:
            raise RuntimeError('Expected a 2 KiB EEPROM')
        eeprom_a = device.read('eeprom', 0, 2048)
        eeprom_b = device.read('eeprom', 0, 2048)
        result['checks']['eeprom_before_sha256'] = [sha(eeprom_a), sha(eeprom_b)]
        if eeprom_a != eeprom_b or eeprom_a != current:
            raise RuntimeError('Connected EEPROM is not the exact installed v3 image')

        original_header = device.read('ram', HEADER_START, 48)
        original_overlay = device.read('ram', OVERLAY_START, restore_length)
        result['checks']['live_header_matches_v3'] = original_header == current[:48]
        live_matches_v3 = (
            original_overlay[:current_length + 4] ==
            current[48:48 + current_length + 4])
        live_matches_v1 = (
            original_overlay[:running_v1_length + 4] ==
            running_v1[48:48 + running_v1_length + 4])
        result['checks']['loaded_v3_overlay_matches'] = live_matches_v3
        result['checks']['loaded_v1_overlay_matches'] = live_matches_v1
        result['checks']['running_overlay_identified_as'] = (
            'v3' if live_matches_v3 else 'v1' if live_matches_v1 else 'unknown')
        if not result['checks']['live_header_matches_v3']:
            raise RuntimeError('Loaded RAM header is not the exact v3 header')
        if not (live_matches_v3 or live_matches_v1):
            raise RuntimeError('Loaded RAM code/checksum matches neither saved v1 nor v3')

        usb = USB()
        result['checks']['get_def_before'] = read_defaults(usb)
        usb.close()
        usb = None

        old_flags = original_header[4]
        disabled_flags = old_flags & ~HOOK_MASK
        touched = True
        device.exchange(0xB6, HEADER_START + 4, disabled_flags)
        time.sleep(0.03)
        if device.read('ram', HEADER_START + 4, 1) != bytes((disabled_flags,)):
            raise RuntimeError('Could not disable overlay callbacks for RAM staging')

        staged_header = bytearray(candidate[:48])
        staged_header[4] = disabled_flags
        write_ram(device, HEADER_START, bytes(staged_header))
        write_ram(device, OVERLAY_START,
                  candidate[48:48 + candidate_length + 4])
        if device.read('ram', HEADER_START, 48) != bytes(staged_header):
            raise RuntimeError('Staged RAM header readback mismatch')
        if device.read('ram', OVERLAY_START, candidate_length + 4) != \
                candidate[48:48 + candidate_length + 4]:
            raise RuntimeError('Staged RAM code/checksum readback mismatch')

        device.exchange(0xB6, HEADER_START + 4, candidate[4])
        time.sleep(0.05)
        if device.read('ram', HEADER_START, 48) != candidate[:48]:
            raise RuntimeError('Could not enable the staged v4 header')
        result['checks']['v4_overlay_active_in_ram'] = True

        usb = USB()
        result['checks']['get_def_after'] = read_defaults(usb)
        result['checks']['candidate_code_after_requests_matches'] = (
            device.read('ram', OVERLAY_START, candidate_length + 4) ==
            candidate[48:48 + candidate_length + 4])
    except BaseException as error:
        operation_error = repr(error)
    finally:
        if usb is not None:
            usb.close()
        if touched and original_header is not None and original_overlay is not None:
            result['restoration']['attempted'] = True
            try:
                disabled_flags = original_header[4] & ~HOOK_MASK
                device.exchange(0xB6, HEADER_START + 4, disabled_flags)
                time.sleep(0.03)
                restore_header = bytearray(original_header)
                restore_header[4] = disabled_flags
                write_ram(device, HEADER_START, bytes(restore_header))
                write_ram(device, OVERLAY_START, original_overlay)
                device.exchange(0xB6, HEADER_START + 4, original_header[4])
                time.sleep(0.03)
                result['restoration']['header_matches'] = (
                    device.read('ram', HEADER_START, 48) == original_header)
                result['restoration']['overlay_span_matches'] = (
                    device.read('ram', OVERLAY_START, restore_length) == original_overlay)
                eeprom_a = device.read('eeprom', 0, 2048)
                eeprom_b = device.read('eeprom', 0, 2048)
                result['restoration']['eeprom_sha256'] = [sha(eeprom_a), sha(eeprom_b)]
                result['restoration']['eeprom_unchanged'] = (
                    eeprom_a == eeprom_b == current)
                result['restoration']['verified'] = all((
                    result['restoration']['header_matches'],
                    result['restoration']['overlay_span_matches'],
                    result['restoration']['eeprom_unchanged'],
                ))
            except BaseException as error:
                result['restoration']['error'] = repr(error)
                result['restoration']['verified'] = False
                result['restoration']['recovery'] = (
                    'Power-cycle to reload the untouched v3 EEPROM image.')
        device.close()

    if operation_error:
        result['operation_error'] = operation_error
    result['status'] = 'passed' if (
        not operation_error and result['checks'].get('v4_overlay_active_in_ram') and
        result['checks'].get('candidate_code_after_requests_matches') and
        all(item['matches'] for item in result['checks'].get('get_def_after', {}).values()) and
        result['restoration'].get('verified')
    ) else 'failed: qualification or restoration check did not pass'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    if result['status'] != 'passed':
        raise RuntimeError(result['status'] + (f"; {operation_error}" if operation_error else ''))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))
