#!/usr/bin/env python3
"""Temporary FEBA=08 probe with live HDMI; restore RAM byte and verify EEPROM."""
import hashlib, json, signal, subprocess, time
from pathlib import Path
from ms2109_hid import Device

OUT = Path('artifacts/no-signal-feba/live-signal-02')
EXPECTED_EEPROM = '83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82'

def capture(name):
    log_path=OUT/f'{name}.log'; video_path=OUT/f'{name}.mkv'
    with log_path.open('w') as log:
        child=subprocess.Popen(['ffmpeg','-nostdin','-hide_banner','-f','avfoundation','-framerate','5',
            '-video_size','1920x1080','-pixel_format','yuyv422','-i','usb video:none','-t','4','-an',
            '-r','5','-c:v','ffv1',str(video_path)],stdout=log,stderr=log)
        time.sleep(1)
        if child.poll() is not None: raise RuntimeError(f'{name}: stream failed to start; inspect log')
        child.wait(timeout=15)
    if child.returncode: raise RuntimeError(f'{name}: capture failed; inspect log')
    subprocess.run(['ffmpeg','-nostdin','-v','error','-sseof','-0.5','-i',str(video_path),'-frames:v','1',
                    '-update','1',str(OUT/f'{name}.png')],check=True,timeout=10)
    return hashlib.sha256((OUT/f'{name}.png').read_bytes()).hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    d=Device(); original=None; wrote=False; result={'scope':'FEBA RAM only; active HDMI; AVFoundation YUY2','stages':[]}
    def save(): (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    def interrupted(sig,frame): raise RuntimeError(f'interrupted by signal {sig}')
    signal.signal(signal.SIGTERM,interrupted)
    try:
        d.identify_eeprom(); image=d.read('eeprom',0,d.eeprom_size)
        digest=hashlib.sha256(image).hexdigest(); result['eeprom_before_sha256']=digest
        if digest!=EXPECTED_EEPROM: raise RuntimeError('EEPROM identity changed; refusing write')
        original=d.read('ram',0xfeba,1)[0]; result['feba_original']=original
        result['f92c_original']=d.read('ram',0xf92c,1)[0]
        if original!=0 or result['f92c_original']!=0x20: raise RuntimeError('Unexpected register baseline; refusing write')
        save()
        result['stages'].append({'name':'baseline','feba':original,'frame_sha256':capture('baseline')}); save()
        wrote=True; d.exchange(0xb6,0xfeba,0x08)
        result['feba_after_write']=d.read('ram',0xfeba,1)[0]; save()
        if result['feba_after_write']!=0x08: raise RuntimeError('FEBA=08 readback failed')
        frame_hash=capture('feba-08')
        result['feba_after_capture']=d.read('ram',0xfeba,1)[0]
        if result['feba_after_capture']!=0x08: raise RuntimeError('FEBA changed during active-signal capture')
        result['stages'].append({'name':'feba-08','feba':0x08,'frame_sha256':frame_hash}); save()
    except BaseException as e:
        result['error']=str(e); save(); raise
    finally:
        if wrote and original is not None:
            d.exchange(0xb6,0xfeba,original)
            result['feba_restored']=d.read('ram',0xfeba,1)[0]
            image=d.read('eeprom',0,d.eeprom_size); result['eeprom_after_sha256']=hashlib.sha256(image).hexdigest()
            result['eeprom_unchanged']=result['eeprom_after_sha256']==result.get('eeprom_before_sha256')
            save()
        d.close()
    if result.get('feba_restored')!=original or not result.get('eeprom_unchanged'):
        raise RuntimeError('RAM restoration or EEPROM verification failed')
    result['stages'].append({'name':'restored','feba':original,'frame_sha256':capture('restored')}); save()
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
