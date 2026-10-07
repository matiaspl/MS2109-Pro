"""Write a validated MS2109 image only when EEPROM exactly matches its backup.

The active RAM firmware is left running. Unplug/replug only after verification.
EEPROM commit is not atomic; retain the backup for external-programmer recovery.
"""
from pathlib import Path
import argparse
import hashlib
import time
from ms2109_hid import Device
from build_patch import validate

p=argparse.ArgumentParser()
p.add_argument('--expected-current',required=True,type=Path)
p.add_argument('--image',required=True,type=Path)
p.add_argument('--apply',action='store_true')
p.add_argument('--readback',type=Path,help='New path for verified full readback; preserves historical captures')
a=p.parse_args()
if a.apply and a.readback and (a.readback.exists() or not a.readback.parent.is_dir()):
    p.error('--readback must be a new file in an existing directory')
old=a.expected_current.read_bytes(); new=a.image.read_bytes()
old_n=validate(old); new_n=validate(new)
if len(old)!=len(new): raise ValueError('EEPROM image sizes differ')
changes=[i for i in range(len(old)) if old[i]!=new[i]]
print(f'{len(changes)} byte writes; target SHA256 {hashlib.sha256(new).hexdigest()}',flush=True)
if not a.apply:
    print('Dry run; add --apply to write.')
    raise SystemExit(0)
d=Device(); f002=None; written=[]
def write_verified(addr,value):
    d.exchange(0xe6,addr,value)
    time.sleep(.02)
    for _ in range(25):
        if d.read('eeprom',addr,1)==bytes([value]): return
        time.sleep(.01)
    raise RuntimeError(f'EEPROM verify failed at {addr:04x}')
try:
    if d.identify_eeprom()!=len(old) or d.read('eeprom',0,len(old))!=old:
        raise RuntimeError('Current EEPROM does not match expected backup; no writes performed')
    f002=d.read('ram',0xf002,1)[0]
    if f002: d.exchange(0xb6,0xf002,0)
    # Prepare unused extension + new checksums first. Then replace entry and
    # finally publish the new length. No boot/reload during this commit window.
    def commit_priority(i):
        if i >= 48+old_n+4:
            return (0, i)
        if i >= 48:
            return (1, i)
        if i in (2,3):
            return (3, i)
        return (2, i)
    order=sorted(changes, key=commit_priority)
    for addr in order:
        written.append(addr)
        write_verified(addr,new[addr])
    actual=d.read('eeprom',0,len(new)); validate(actual)
    if actual!=new: raise RuntimeError('Full image readback mismatch')
    if a.readback:
        with a.readback.open('xb') as output:output.write(actual)
    else:
        Path('artifacts/ms2109-flashed-readback.bin').write_bytes(actual)
    print(f'Full EEPROM verified: {hashlib.sha256(actual).hexdigest()}',flush=True)
except BaseException:
    if written:
        print('Write failed; attempting to restore all modified bytes from backup',flush=True)
        for addr in reversed(written): write_verified(addr,old[addr])
        if d.read('eeprom',0,len(old))!=old:
            raise RuntimeError('Rollback verification failed; keep device powered')
        print('Original EEPROM restored and verified',flush=True)
    raise
finally:
    if f002 is not None and f002: d.exchange(0xb6,0xf002,f002)
    d.close()
