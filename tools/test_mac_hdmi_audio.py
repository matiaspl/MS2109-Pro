"""Controlled HDMI source test; restore FE60 and stop only our playback.

Requires the Mac's default sound output to be the connected HDMI TO USB sink.
The reference is continuous left 1 kHz, right with 500 ms gaps every 2 s.
No EEPROM writes. FE60 semantics remain unconfirmed.
"""
import argparse
import json
import subprocess
import time
import wave
import array
from pathlib import Path
from ms2109_hid import Device

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--experiment',action='store_true')
p.add_argument('--swap-only',action='store_true')
a=p.parse_args()
if not a.experiment:p.error('--experiment required')
profile=json.loads(subprocess.check_output(['system_profiler','SPAudioDataType','-json']))
outputs=[i for group in profile['SPAudioDataType'] for i in group.get('_items',[])
         if i.get('coreaudio_default_audio_output_device')=='spaudio_yes']
if len(outputs)!=1 or outputs[0].get('coreaudio_device_transport')!='coreaudio_device_type_hdmi' or outputs[0]['_name']!='HDMI TO USB':
    raise SystemExit('Default sound output must be HDMI TO USB')
d=Device(); original=d.read('ram',0xfe60,1)[0]; play=None
result={'source':outputs[0],'reference':'artifacts/mac-hdmi-reference.wav','original_fe60':original,'captures':[]}
try:
    if original!=16:raise RuntimeError('Expected FE60=16')
    playlog=open('artifacts/mac-hdmi-playback.log','w')
    play=subprocess.Popen(['afplay','artifacts/mac-hdmi-reference.wav'],stderr=playlog)
    time.sleep(.5)
    sequence=[('swap-baseline',16),('swap01',1),('swap-restored',16)] if a.swap_only else [('baseline',16),('value17',17),('value32',32),('restored',16)]
    for label,value in sequence:
        d.exchange(0xb6,0xfe60,value)
        time.sleep(.1)
        readback=d.read('ram',0xfe60,1)[0]
        capture={'label':label,'value':value,'readback':readback}
        print('Capturing',label,'FE60=',readback,flush=True)
        try:
            cap=subprocess.run(['ffmpeg','-y','-hide_banner','-f','avfoundation','-i',':usb video','-t','4','-vn','-c:a','pcm_s16le',f'artifacts/mac-hdmi-{label}.wav'],capture_output=True,text=True,timeout=10)
            capture['exit']=cap.returncode
            Path(f'artifacts/mac-hdmi-{label}.log').write_text(cap.stderr)
        except subprocess.TimeoutExpired:capture['timeout']=True
        result['captures'].append(capture)
        capture['playback_exit']=play.poll()
        if label.endswith('baseline'):
            with wave.open(f'artifacts/mac-hdmi-{label}.wav','rb') as wav:
                pcm=array.array('h',wav.readframes(wav.getnframes()))
            capture['peak']=max(map(abs,pcm),default=0)
            if capture['peak']<100:raise RuntimeError('No reference tone in baseline; candidate was not tested')
finally:
    d.exchange(0xb6,0xfe60,original)
    result['restored_fe60']=d.read('ram',0xfe60,1)[0]
    d.close()
    if play is not None and play.poll() is None:play.terminate();play.wait()
    if play is not None:
        result['playback_exit']=play.returncode
        playlog.close()
    Path('artifacts/mac-hdmi-swap-test.json' if a.swap_only else 'artifacts/mac-hdmi-control-test.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)
