"""Temporary MOVC USB interrupt hook, restored in finally; no EEPROM writes."""
from ms2109_hid import Device
from pathlib import Path
import time

d = Device()
try:
    d.identify_eeprom()
    if d.read('eeprom', 0x30, 5) != bytes.fromhex('90de0beff0'):
        raise RuntimeError('ROM dump helper is qualified only for the original unpatched firmware')
except BaseException:
    d.close()
    raise
def write(addr, data):
    for i, v in enumerate(data):
        d.exchange(0xb6, addr+i, v)
blob = Path('upstream/ms-tools/cli/asm/dumprom.bin').read_bytes().replace(b'\xde\xad', b'\xcb\xf0')
old = d.read('ram', 0xcc20, len(blob))
hooks = d.read('ram', 0xcbd4, 2)
mailbox = d.read('ram', 0xcbf0, 5)
temp = d.read('ram', 0xd300, 255)
try:
    write(0xcbd4, b'\x00\x00')
    time.sleep(.05)
    write(0xcbf0, b'\x00')
    write(0xcc20, blob)
    write(0xcbd4, b'\x04')
    out = bytearray()
    for addr in range(0, 0xcc00, 255):
        count = min(255, 0xcc00-addr)
        write(0xcbf1, addr.to_bytes(2,'big') + b'\xd3\x00')
        write(0xcbf0, bytes([count]))
        deadline = time.monotonic() + 1
        while d.read('ram', 0xcbf0, 1) != b'\x00':
            if time.monotonic() > deadline:
                raise RuntimeError('ROM hook timed out')
            time.sleep(.01)
        out.extend(d.read('ram', 0xd300, count))
        if addr // 4096 != (addr+count) // 4096:
            print(f'ROM bytes read: {len(out)}', flush=True)
    Path('backups/ms2109-maskrom.bin').write_bytes(out)
finally:
    write(0xcbd4, b'\x00')
    time.sleep(.05)
    write(0xcc20, old)
    write(0xcbf0, mailbox)
    write(0xd300, temp)
    write(0xcbd4, hooks)
    assert d.read('ram', 0xcc20, len(old)) == old
    assert d.read('ram', 0xcbd4, 2) == hooks
    d.close()
    print('Original code and hooks restored', flush=True)
