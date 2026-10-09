"""Reversibly test MS2109 product-string XDATA and EP0 behavior; never write EEPROM."""
from __future__ import annotations
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from ms2109_hid import Device

EXPECTED_EEPROM = '83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82'
PRODUCT_DESC_ADDR = 0xC636
PRODUCT_DESC_ORIGINAL = bytes.fromhex('1403750073006200200076006900640065006f00')
PRODUCT_DESC_CANDIDATE = bytes.fromhex(
    '16034d00530032003100300039002d00500072006f00')


class EP0:
    def __init__(self):
        self.lib = C.CDLL('/opt/homebrew/lib/libusb-1.0.dylib')
        self.lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
        self.lib.libusb_init.restype = C.c_int
        self.lib.libusb_open_device_with_vid_pid.argtypes = [C.c_void_p,C.c_uint16,C.c_uint16]
        self.lib.libusb_open_device_with_vid_pid.restype = C.c_void_p
        self.lib.libusb_control_transfer.argtypes = [C.c_void_p,C.c_uint8,C.c_uint8,
            C.c_uint16,C.c_uint16,C.POINTER(C.c_ubyte),C.c_uint16,C.c_uint]
        self.lib.libusb_control_transfer.restype = C.c_int
        self.lib.libusb_close.argtypes = [C.c_void_p]
        self.lib.libusb_exit.argtypes = [C.c_void_p]
        self.ctx = C.c_void_p()
        rc = self.lib.libusb_init(C.byref(self.ctx))
        if rc:
            raise RuntimeError(f'libusb_init failed: {rc}')
        self.handle = self.lib.libusb_open_device_with_vid_pid(self.ctx,0x534d,0x2109)
        if not self.handle:
            self.close()
            raise RuntimeError('libusb could not open the enumerated MS2109')

    def product(self):
        buf = (C.c_ubyte * 64)()
        n = self.lib.libusb_control_transfer(self.handle,0x80,6,0x0302,0x0409,buf,64,3000)
        if n < 0:
            raise RuntimeError(f'GET_DESCRIPTOR string 2 failed: {n}')
        return bytes(buf[:n])

    def close(self):
        if getattr(self,'handle',None):
            self.lib.libusb_close(self.handle)
            self.handle = None
        if getattr(self,'ctx',None):
            self.lib.libusb_exit(self.ctx)
            self.ctx = None


def write_ram(device, address, data):
    for offset, value in enumerate(data):
        device.exchange(0xB6, address + offset, value)


def run(output):
    if output.exists():
        raise RuntimeError(f'Refusing to overwrite {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    device = Device()
    ep0 = None
    original = None
    changed = False
    result = {'scope':'volatile XDATA product-string probe; EEPROM is read-only',
              'product_xdata_address':hex(PRODUCT_DESC_ADDR),
              'candidate_descriptor_hex':PRODUCT_DESC_CANDIDATE.hex(),
              'candidate_startup_hook_executed':False,
              'restoration':{'attempted':False}}
    try:
        if device.identify_eeprom() != 2048:
            raise RuntimeError('Expected 2 KiB EEPROM')
        eeprom = device.read('eeprom',0,2048)
        result['eeprom_sha256_before'] = hashlib.sha256(eeprom).hexdigest()
        if result['eeprom_sha256_before'] != EXPECTED_EEPROM:
            raise RuntimeError('Installed EEPROM differs from the verified rollback image')
        original = device.read('ram',PRODUCT_DESC_ADDR,len(PRODUCT_DESC_CANDIDATE))
        result['product_descriptor_ram_before'] = original.hex()
        ep0 = EP0()
        before = ep0.product()
        result['ep0_product_before_hex'] = before.hex()
        if original[:len(PRODUCT_DESC_ORIGINAL)] != PRODUCT_DESC_ORIGINAL:
            raise RuntimeError('Product descriptor XDATA differs from the pinned ROM snapshot')
        if before != PRODUCT_DESC_ORIGINAL:
            raise RuntimeError('EP0 product descriptor differs from the expected ROM string')
        changed = True
        write_ram(device,PRODUCT_DESC_ADDR,PRODUCT_DESC_CANDIDATE)
        during = device.read('ram',PRODUCT_DESC_ADDR,len(PRODUCT_DESC_CANDIDATE))
        result['product_descriptor_ram_during_hex'] = during.hex()
        result['ep0_product_during_hex'] = ep0.product().hex()
        result['ep0_reflected_ram_patch'] = result['ep0_product_during_hex'] == PRODUCT_DESC_CANDIDATE.hex()
        result['status'] = ('passed: EP0 reflected the volatile MS2109-Pro descriptor' if
                            result['ep0_reflected_ram_patch'] else
                            'partial: XDATA patch read back, but EP0 did not reflect it')
    finally:
        if ep0 is not None:
            ep0.close()
        if changed and original is not None:
            result['restoration']['attempted'] = True
            write_ram(device,PRODUCT_DESC_ADDR,original)
            result['restoration']['product_descriptor_ram_restored'] = (
                device.read('ram',PRODUCT_DESC_ADDR,len(original)) == original)
        eeprom1 = device.read('eeprom',0,2048)
        eeprom2 = device.read('eeprom',0,2048)
        result['eeprom_sha256_read1'] = hashlib.sha256(eeprom1).hexdigest()
        result['eeprom_sha256_read2'] = hashlib.sha256(eeprom2).hexdigest()
        result['eeprom_unchanged'] = (eeprom1 == eeprom2 and result['eeprom_sha256_read1'] == EXPECTED_EEPROM)
        if changed and not result['restoration'].get('product_descriptor_ram_restored'):
            result['status'] = 'FAILED: product descriptor RAM restoration failed'
        if not result['eeprom_unchanged']:
            result['status'] = 'FAILED: EEPROM changed or reads disagree'
        device.close()
        output.write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output),indent=2))
