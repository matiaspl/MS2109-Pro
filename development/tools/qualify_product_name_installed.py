"""Reset the installed MS2109-Pro image and verify its USB product string."""
from __future__ import annotations
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from ms2109_hid import Device

CANDIDATE_SHA = '543d35dc33ff9f0bf60fe24066032c56aa40b23b7c2b58207c7afdb955f41961'
PRODUCT = 'MS2109-Pro'


class USB:
    def __init__(self):
        self.lib=C.CDLL('/opt/homebrew/lib/libusb-1.0.dylib')
        self.lib.libusb_init.argtypes=[C.POINTER(C.c_void_p)];self.lib.libusb_init.restype=C.c_int
        self.lib.libusb_open_device_with_vid_pid.argtypes=[C.c_void_p,C.c_uint16,C.c_uint16]
        self.lib.libusb_open_device_with_vid_pid.restype=C.c_void_p
        self.lib.libusb_control_transfer.argtypes=[C.c_void_p,C.c_uint8,C.c_uint8,C.c_uint16,C.c_uint16,
                                                   C.POINTER(C.c_ubyte),C.c_uint16,C.c_uint]
        self.lib.libusb_control_transfer.restype=C.c_int
        self.lib.libusb_reset_device.argtypes=[C.c_void_p];self.lib.libusb_reset_device.restype=C.c_int
        self.lib.libusb_close.argtypes=[C.c_void_p];self.lib.libusb_exit.argtypes=[C.c_void_p]
        self.ctx=C.c_void_p();rc=self.lib.libusb_init(C.byref(self.ctx))
        if rc:raise RuntimeError(f'libusb_init failed: {rc}')
        self.handle=None

    def open(self):
        self.handle=self.lib.libusb_open_device_with_vid_pid(self.ctx,0x534d,0x2109)
        return bool(self.handle)

    def product(self):
        buf=(C.c_ubyte*64)()
        n=self.lib.libusb_control_transfer(self.handle,0x80,6,0x0302,0x0409,buf,64,3000)
        if n<0:raise RuntimeError(f'GET_DESCRIPTOR string 2 failed: {n}')
        return bytes(buf[:n])

    def reset(self):return self.lib.libusb_reset_device(self.handle)

    def close_device(self):
        if self.handle:self.lib.libusb_close(self.handle);self.handle=None

    def close(self):
        self.close_device()
        if self.ctx:self.lib.libusb_exit(self.ctx);self.ctx=None


def read_eeprom():
    d=Device()
    try:
        if d.identify_eeprom()!=2048:raise RuntimeError('Expected 2 KiB EEPROM')
        data=d.read('eeprom',0,2048)
        return hashlib.sha256(data).hexdigest()
    finally:d.close()


def run(output):
    if output.exists():raise RuntimeError(f'Refusing to overwrite {output}')
    result={'scope':'post-install USB reset and product-string verification',
            'candidate_sha256':CANDIDATE_SHA,'product_expected':PRODUCT}
    before=read_eeprom();result['eeprom_sha256_before_reset']=before
    if before!=CANDIDATE_SHA:raise RuntimeError('Installed EEPROM does not match the candidate')
    usb=USB()
    try:
        if not usb.open():raise RuntimeError('Could not open the installed MS2109')
        result['product_before_reset_hex']=usb.product().hex()
        rc=usb.reset();result['libusb_reset_device_result']=rc
        if rc:raise RuntimeError(f'USB reset failed: {rc}')
        usb.close_device()
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            time.sleep(.5)
            if usb.open():
                try:
                    product=usb.product()
                    if product:
                        result['product_after_reset_hex']=product.hex()
                        break
                except Exception:
                    usb.close_device()
        else:
            raise RuntimeError('Device did not return after USB reset')
        if len(product)<2 or product[0]!=len(product) or product[1]!=3:
            raise RuntimeError('Malformed product string descriptor after reset')
        decoded=product[2:].decode('utf-16le')
        result['product_after_reset']=decoded
        result['product_matches']=decoded==PRODUCT
        result['eeprom_sha256_after_reset']=read_eeprom()
        result['eeprom_unchanged_candidate']=(result['eeprom_sha256_after_reset']==CANDIDATE_SHA)
        result['status']='passed' if result['product_matches'] and result['eeprom_unchanged_candidate'] else 'failed: verification mismatch'
    finally:
        usb.close()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.output),indent=2))
