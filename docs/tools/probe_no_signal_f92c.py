#!/usr/bin/env python3
"""Bounded F92C 20/30 experiment; restore exact original byte; never write EEPROM."""
import argparse
import hashlib
import json
import signal
import subprocess
import time
from pathlib import Path
from ms2109_hid import Device


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--hdmi-disconnected',action='store_true',required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    result={'scope':'F92C only, temporary writes; AVFoundation delivered frames', 'stages':[]}
    def save(): (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    def interrupted(signum,frame): raise RuntimeError(f'Interrupted by signal {signum}')
    signal.signal(signal.SIGTERM,interrupted)
    d=Device(); child=None; original=None; written=False
    def snapshot():
        return {f'{a:04x}':d.read('ram',a,n).hex() for a,n in
                ((0xf92c,1),(0xfeba,1),(0xc6aa,1),(0xf1fa,6),(0xfe90,4),(0xc6a0,8),(0xcbd4,2))}
    try:
        d.identify_eeprom()
        before=d.read('eeprom',0,d.eeprom_size)
        result['eeprom_before_sha256']=hashlib.sha256(before).hexdigest()
        result['before']=snapshot(); original=int(result['before']['f92c'],16)
        if original not in (0x20,0x30): raise RuntimeError(f'Unexpected F92C {original:02x}; no test writes')
        save()
        for name,value in [('baseline',None),('f92c-20',0x20),('f92c-30',0x30),('restored',original)]:
            stage={'name':name,'requested':value,'before_capture':snapshot()};result['stages'].append(stage);save()
            with (args.output/(name+'.log')).open('w') as log:
                child=subprocess.Popen(['ffmpeg','-nostdin','-hide_banner','-f','avfoundation',
                    '-framerate','5','-video_size','1920x1080','-pixel_format','yuyv422',
                    '-i','usb video:none','-t','4','-an','-r','5','-c:v','ffv1',str(args.output/(name+'.mkv'))],
                    stdout=log,stderr=log)
                time.sleep(1)
                if child.poll() is not None: raise RuntimeError(f'{name}: capture exited before write')
                if value is not None:
                    written=True;d.exchange(0xb6,0xf92c,value)
                stage['after_write']=snapshot();save()
                child.wait(timeout=15)
                stage['returncode']=child.returncode;child=None
            stage['after_capture']=snapshot();save()
            if stage['returncode']: raise RuntimeError(f'{name}: capture failed')
            subprocess.run(['ffmpeg','-nostdin','-v','error','-sseof','-0.5','-i',str(args.output/(name+'.mkv')),
                            '-frames:v','1','-update','1',str(args.output/(name+'.png'))],check=True,timeout=10)
            if value is not None and (stage['after_write']['f92c']!=f'{value:02x}' or stage['after_capture']['f92c']!=f'{value:02x}'):
                raise RuntimeError(f'{name}: requested byte was not retained; stop before further writes')
    except BaseException as error:
        result['error']=str(error);raise
    finally:
        try:
            if child and child.poll() is None:
                child.terminate()
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill();child.wait()
            if original is not None:
                if written: d.exchange(0xb6,0xf92c,original)
                result['after']=snapshot()
                result['register_restored']=result['after']['f92c']==f'{original:02x}'
                after=d.read('eeprom',0,d.eeprom_size)
                result['eeprom_after_sha256']=hashlib.sha256(after).hexdigest()
                result['eeprom_unchanged']=after==before
        except BaseException as error:
            result['restoration_error']=str(error)
            raise
        finally: d.close();save()
    if not result.get('register_restored') or not result.get('eeprom_unchanged'):
        raise RuntimeError('Post-test verification failed')
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
