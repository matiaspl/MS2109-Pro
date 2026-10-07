from audio_ram_probe import Probe
import subprocess,json
from pathlib import Path
# Rejected research candidate. Never apply as an alignment fix.
import sys
if '--experiment' not in sys.argv:
    raise SystemExit('Rejected RAM experiment; explicit --experiment required. See report.')

p=Probe(); old=None
try:
    old=p.command(2)
    original=old['a2'] | old['a3']<<8
    print('Endpoint original:',old,flush=True)
    candidate=original+2
    changed=p.command(2,candidate)
    print('Endpoint candidate:',changed,flush=True)
    result=subprocess.run(['ffmpeg','-hide_banner','-f','avfoundation','-i',':usb video','-t','4','-vn','-c:a','pcm_s16le','artifacts/audio-endpoint-plus2.wav'],capture_output=True,text=True,timeout=15)
    print(result.stderr[-1800:],flush=True)
    print('Endpoint after capture:',p.command(2),flush=True)
    Path('artifacts/audio-endpoint-plus2.json').write_text(json.dumps({'original':old,'candidate':changed,'capture_returncode':result.returncode},indent=2)+'\n')
finally:
    if old is not None: print('Restored endpoint:',p.command(2,old['a2']|old['a3']<<8),flush=True)
    p.close(); print('Original common hook restored',flush=True)
