#!/usr/bin/env python3
"""Read-only verification of the calibrated MS2109 EEPROM and active startup.

Run outside the macOS shell sandbox after unplugging/replugging USB. No RAM,
EEPROM or picture-control writes. Exit 1 if the new image is not fully active;
--allow-pending permits a verified EEPROM with a pending power cycle.
"""
import argparse
import hashlib
import json
from pathlib import Path
from build_patch import build, validate
from ms2109_hid import Device

ROOT=Path(__file__).resolve().parents[1]


def verify(image):
    return verify_profile(image,'installed')


def verify_profile(image,profile):
    expected,_,_=build((ROOT/'backups/ms2109-original.bin').read_bytes(),
                       channel_order=True,
                       calibrated_color=profile=='installed',
                       calibrated_color_v2=profile=='v2',
                       rom=(ROOT/'backups/ms2109-maskrom.bin').read_bytes())
    if image!=expected:raise ValueError(f'Image differs from the {profile} calibrated color/channel-order build')
    n=validate(image);d=Device()
    try:
        size=d.identify_eeprom()
        if size!=len(image):raise ValueError('Unexpected EEPROM capacity')
        actual=d.read('eeprom',0,size);validate(actual)
        fields={'current_procamp':(0xc6a0,bytes.fromhex('ee ff 95 00 00 00 93 00')),
                'hardware_procamp':(0xfe90,bytes.fromhex('ee 95 93 00')),
                'mjpeg_color_descriptor':(0xc2a4,bytes.fromhex('06 24 0d 01 01 01')),
                'yuy2_color_descriptor':(0xc43b,bytes.fromhex('06 24 0d 01 01 01')),
                'audio_channel_order':(0xfe60,b'\x01')}
        checks={}
        for name,(address,wanted) in fields.items():
            value=d.read('ram',address,len(wanted))
            checks[name]={'address':hex(address),'actual':value.hex(),'expected':wanted.hex(),'matches':value==wanted}
        active_header=d.read('ram',0xcbd0,48)
        code=d.read('ram',0xcc00,n)
        header_ok=active_header==image[:48];code_ok=code==image[48:48+n]
        return {'eeprom_matches_image':actual==image,'eeprom_sha256':hashlib.sha256(actual).hexdigest(),
                'expected_sha256':hashlib.sha256(image).hexdigest(),'loaded_header_matches':header_ok,
                'loaded_code_matches':code_ok,'active_code_length':int.from_bytes(active_header[2:4],'big'),
                'expected_code_length':n,'checks':checks,
                'startup_active':header_ok and code_ok and all(check['matches'] for check in checks.values()),
                'f002':d.read('ram',0xf002,1).hex(),
                'verification_scope':'HID EEPROM/RAM readback; host decoder color handling requires frame capture',
                'profile':profile}
    finally:d.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',required=True,type=Path)
    p.add_argument('--profile',choices=['installed','v2'],default='installed',help='installed calibrated image or opt-in shared-matrix v2 candidate')
    p.add_argument('--output',type=Path);p.add_argument('--allow-pending',action='store_true');args=p.parse_args()
    if args.output and args.output.exists():p.error('Use a new output path; preserve prior observations')
    result=verify_profile(args.image.read_bytes(),args.profile);text=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    print(text,end='')
    if not result['eeprom_matches_image']:raise SystemExit(1)
    if not result['startup_active']:
        print('Calibrated startup not yet active. Unplug/replug USB, then rerun this read-only check.')
        if not args.allow_pending:raise SystemExit(1)


if __name__=='__main__':main()
