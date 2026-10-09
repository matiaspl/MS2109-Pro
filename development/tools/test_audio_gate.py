"""Test the ROM's FE61 audio-rate control bit in RAM; restore in finally."""
import json
import subprocess
import time
from pathlib import Path
from ms2109_hid import Device

# Rejected research candidate. Never apply as an alignment fix.
import sys
if '--experiment' not in sys.argv:
    raise SystemExit('Rejected RAM experiment; explicit --experiment required. See report.')

d = Device()
child = None
original = d.read('ram', 0xfe61, 1)[0]
result = {'register': 'FE61', 'original': original,
          'basis': 'ROM 3EEC sets bit 0 when input/output sample rates differ'}
try:
    child = subprocess.Popen([
        'ffmpeg', '-hide_banner', '-f', 'avfoundation', '-i', ':usb video',
        '-t', '6', '-vn', '-c:a', 'pcm_s16le', 'artifacts/audio-rate-gate.wav'],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    time.sleep(2)
    d.exchange(0xb6, 0xfe61, original & ~1)
    result['disabled_readback'] = d.read('ram', 0xfe61, 1)[0]
    time.sleep(.02)
    d.exchange(0xb6, 0xfe61, original)
    result['enabled_readback'] = d.read('ram', 0xfe61, 1)[0]
    _, err = child.communicate(timeout=15)
    result['returncode'] = child.returncode
    print(err[-600:])
finally:
    if child is not None and child.poll() is None:
        child.kill()
        child.wait()
    d.exchange(0xb6, 0xfe61, original)
    result['restored'] = d.read('ram', 0xfe61, 1)[0] == original
    d.close()
    Path('artifacts/audio-rate-gate.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result, flush=True)
