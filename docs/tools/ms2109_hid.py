"""MS2109 factory HID transport, based on A-Dunstan's feature reports."""
import ctypes as C
import ctypes.util
import hashlib
import json
from pathlib import Path

class Device:
    def __init__(self):
        self.lib = C.CDLL(ctypes.util.find_library('hidapi') or '/opt/homebrew/lib/libhidapi.dylib')
        self.lib.hid_init()
        if hasattr(self.lib, 'hid_darwin_set_open_exclusive'):
            self.lib.hid_darwin_set_open_exclusive(0)
        self.lib.hid_open.argtypes = [C.c_ushort, C.c_ushort, C.c_wchar_p]
        self.lib.hid_open.restype = C.c_void_p
        self.lib.hid_error.argtypes = [C.c_void_p]
        self.lib.hid_error.restype = C.c_wchar_p
        self.lib.hid_close.argtypes = [C.c_void_p]
        for name in ('hid_send_feature_report', 'hid_get_feature_report'):
            fn = getattr(self.lib, name)
            fn.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
            fn.restype = C.c_int
        self.dev = self.lib.hid_open(0x534d, 0x2109, None)
        if not self.dev:
            raise RuntimeError(self.lib.hid_error(None) or 'Cannot open 534d:2109')
        self.eeprom_size = 2048
        if self.read('ram', 0xf800, 3) != bytes.fromhex('a7109a'):
            self.close()
            raise RuntimeError('MS2109 silicon ID mismatch')
    def close(self):
        if self.dev:
            self.lib.hid_close(self.dev)
            self.dev = None
    def exchange(self, cmd, addr, value=0):
        b = (C.c_ubyte * 9)(0, cmd, addr >> 8, addr & 255, value, 0, 0, 0,
                                int(self.eeprom_size > 2048) if cmd in (0xe5, 0xe6) else 0)
        n = self.lib.hid_send_feature_report(self.dev, b, 9)
        if n != 9:
            raise RuntimeError(f'HID send {n}: {self.lib.hid_error(self.dev)}')
        if cmd in (0xb5, 0xe5):
            b[0] = 0
            n = self.lib.hid_get_feature_report(self.dev, b, 9)
            if n != 9 or bytes(b)[1:4] != bytes((cmd, addr >> 8, addr & 255)):
                raise RuntimeError(f'Invalid HID response {n}: {bytes(b).hex()}')
            return b[4]
    def sfr(self, addr, value=None):
        if not 0x80 <= addr <= 0xff:
            raise ValueError('SFR address must be 80-FF')
        cmd = 0xc5 if value is None else 0xc6
        b = (C.c_ubyte * 9)(0, cmd, addr, value or 0, 0, 0, 0, 0, 0)
        if self.lib.hid_send_feature_report(self.dev, b, 9) != 9:
            raise RuntimeError('SFR feature send failed')
        if value is None:
            b[0] = 0
            if self.lib.hid_get_feature_report(self.dev, b, 9) != 9 or b[1] != cmd or b[2] != addr:
                raise RuntimeError('Invalid SFR reply')
            return b[3]

    def read(self, region, addr, count):
        cmd = {'ram': 0xb5, 'eeprom': 0xe5}[region]
        return bytes(self.exchange(cmd, i) for i in range(addr, addr + count))
    def identify_eeprom(self):
        magic = self.read('ram', 0xcbd0, 2)
        if magic not in (b'\xa5\x5a', b'\x96\x69'):
            raise RuntimeError(f'Unknown EEPROM magic: {magic.hex()}')
        self.eeprom_size = 2048 if magic == b'\xa5\x5a' else 4096
        if self.read('eeprom', 0, 2) != magic:
            raise RuntimeError('EEPROM and RAM signatures disagree')
        return self.eeprom_size

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['inspect', 'backup'])
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    d = Device()
    try:
        size = d.identify_eeprom()
        status = {'chip': 'MS2109', 'eeprom_size': size}
        for addr, count in ((0xc4c1, 11), (0xc6a0, 8), (0xfe90, 4), (0xcbd0, 48)):
            status[f'{addr:04x}'] = d.read('ram', addr, count).hex()
        print(json.dumps(status, indent=2), flush=True)
        if a.command == 'backup':
            if not a.output:
                p.error('--output is required')
            if a.output.exists():
                raise RuntimeError('Refusing to overwrite backup')
            first = d.read('eeprom', 0, size)
            second = d.read('eeprom', 0, size)
            if first != second:
                raise RuntimeError('Two complete EEPROM reads disagree')
            a.output.write_bytes(first)
            status['sha256'] = hashlib.sha256(first).hexdigest()
            a.output.with_suffix('.json').write_text(json.dumps(status, indent=2) + '\n')
            print(f'Verified backup: {a.output} SHA256 {status["sha256"]}')
    finally:
        d.close()
