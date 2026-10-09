from audio_ram_probe import Probe
import subprocess,time,json
from pathlib import Path
# Rejected research candidate. Never apply as an alignment fix.
import sys
if '--experiment' not in sys.argv:
    raise SystemExit('Rejected RAM experiment; explicit --experiment required. See report.')

p=Probe(); child=None
try:
    print('Endpoint baseline:',p.command(2),flush=True)
    child=subprocess.Popen(['ffmpeg','-hide_banner','-f','avfoundation','-i',':usb video','-t','5','-vn','-c:a','pcm_s16le','artifacts/audio-fifo-dma-insert2.wav'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    time.sleep(2)
    print('FIFO operation:',p.command(2,action=5),flush=True)
    _,err=child.communicate(timeout=12)
    print(err[-900:],flush=True)
    Path('artifacts/audio-fifo-dma-insert2.json').write_text(json.dumps({'action':5,'returncode':child.returncode},indent=2)+'\n')
finally:
    if child is not None and child.poll() is None:
        child.kill(); child.wait()
    p.close(); print('Original hook restored',flush=True)
