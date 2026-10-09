"""Test FE60=32 as an inferred audio-word control; restore the exact byte.

FE60 lies beside the ROM's FE61..67 rate converter registers and reads 16.
There is no known register definition: the word-size interpretation is a
hypothesis, not documentation. No EEPROM writes.
"""
import argparse
import json
import subprocess
from pathlib import Path
from ms2109_hid import Device

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--experiment', action='store_true')
p.add_argument('--value', type=int, choices=(17,32), default=32)
args = p.parse_args()
if not args.experiment:
    p.error('Explicit --experiment required for this unqualified RAM candidate')
d = Device()
result = {'register': 'FE60', 'candidate': args.value, 'semantics': 'unconfirmed'}
original = d.read('ram', 0xfe60, 1)[0]
result['original'] = original
try:
    if original != 16:
        raise RuntimeError('Expected FE60=16; refusing experiment on other state')
    d.exchange(0xb6, 0xfe60, args.value)
    actual = d.read('ram', 0xfe60, 1)[0]
    result['readback'] = actual
    if actual == args.value:
        try:
            cap = subprocess.run([
                'ffmpeg', '-hide_banner', '-f', 'avfoundation', '-i', ':usb video',
                '-t', '4', '-vn', '-c:a', 'pcm_s16le', f'artifacts/audio-word{args.value}.wav'],
                capture_output=True, text=True, timeout=12)
            result['capture_exit'] = cap.returncode
            result['capture_log'] = cap.stderr
        except subprocess.TimeoutExpired:
            result['capture_timeout'] = True
    else:
        result['capture_skipped'] = 'Candidate value did not read back'
finally:
    d.exchange(0xb6, 0xfe60, original)
    result['restored_readback'] = d.read('ram', 0xfe60, 1)[0]
    d.close()
    Path(f'artifacts/audio-word-control-{args.value}.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='capture_log'}, indent=2))
