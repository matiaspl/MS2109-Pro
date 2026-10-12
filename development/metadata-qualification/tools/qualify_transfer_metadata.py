#!/usr/bin/env python3
"""Resumable MS2109 metadata qualification. Never writes EEPROM or raw frames."""
from __future__ import annotations
import argparse
import base64
import ctypes as C
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'builder'))
from transfer_metadata import (edit_edid, validate_edid, parse_configuration,
                             transfer_value, edid_eeprom_candidate,
                             transfer_eeprom_candidate, manifest)
from ms2109_hid import Device

SETTING={'brightness':-17,'contrast':148,'hue':0,'saturation':146}
PATTERN_DIR=ROOT/'firmware/patterns'

def sha(b): return hashlib.sha256(b).hexdigest()
def save(path,value): path.write_text(json.dumps(value,indent=2)+'\n')

class USB:
    def __init__(self):
        self.lib=C.CDLL(ctypes.util.find_library('usb-1.0') or '/opt/homebrew/lib/libusb-1.0.dylib')
        self.lib.libusb_init.argtypes=[C.POINTER(C.c_void_p)]
        self.lib.libusb_open_device_with_vid_pid.argtypes=[C.c_void_p,C.c_uint16,C.c_uint16]
        self.lib.libusb_open_device_with_vid_pid.restype=C.c_void_p
        self.lib.libusb_control_transfer.argtypes=[C.c_void_p,C.c_uint8,C.c_uint8,C.c_uint16,C.c_uint16,C.c_void_p,C.c_uint16,C.c_uint]
        self.lib.libusb_close.argtypes=[C.c_void_p];self.lib.libusb_exit.argtypes=[C.c_void_p]
        self.ctx=C.c_void_p();self.handle=None
        if self.lib.libusb_init(C.byref(self.ctx)): raise RuntimeError('libusb init failed')
        self.handle=self.lib.libusb_open_device_with_vid_pid(self.ctx,0x534d,0x2109)
        if not self.handle:self.close();raise RuntimeError('EP0 open failed: actual administrator access may be required')
    def descriptor(self,kind,length):
        buf=(C.c_ubyte*length)()
        n=self.lib.libusb_control_transfer(self.handle,0x80,6,kind<<8,0,buf,length,3000)
        if n<0:raise RuntimeError(f'GET_DESCRIPTOR {kind} failed: {n}')
        return bytes(buf[:n])
    def configuration(self,kind=2):
        header=self.descriptor(kind,9)
        if len(header)!=9:raise RuntimeError('Incomplete configuration header')
        result=self.descriptor(kind,int.from_bytes(header[2:4],'little'))
        parse_configuration(result)
        return result
    def reset(self):
        self.lib.libusb_reset_device.argtypes=[C.c_void_p]
        n=self.lib.libusb_reset_device(self.handle)
        if n:raise RuntimeError(f'USB reset returned {n}')
    def close(self):
        if self.handle:self.lib.libusb_close(self.handle);self.handle=None
        if self.ctx:self.lib.libusb_exit(self.ctx);self.ctx=None

def source_edid():
    raw=subprocess.check_output(['/usr/sbin/ioreg','-l','-w','0'],text=True,timeout=20)
    candidates=[]
    for line in raw.splitlines():
        if '"EDID"=<' in line and 'HDMI TO USB' in line:
            match=re.search(r'"EDID"=<([0-9a-fA-F]+)>',line)
            if match:
                b=bytes.fromhex(match[1]);validate_edid(b);candidates.append(b)
    unique=set(candidates)
    if len(unique)!=1:raise RuntimeError(f'Expected one unambiguous HDMI TO USB source EDID, found {len(unique)}')
    return unique.pop()

def baseline_guard(out):
    baseline=(out/'baseline-eeprom.bin').read_bytes()
    d=Device()
    try:
        if d.identify_eeprom()!=len(baseline) or d.read('eeprom',0,len(baseline))!=baseline:
            raise RuntimeError('Live EEPROM changed from this run’s rollback baseline')
    finally:d.close()
    return baseline

def snapshot(out):
    out.mkdir(parents=True,exist_ok=True)
    if (out/'snapshot.json').exists():raise RuntimeError('Snapshot already exists; use a fresh directory')
    d=Device();u=None
    try:
        size=d.identify_eeprom();first=d.read('eeprom',0,size);second=d.read('eeprom',0,size)
        if first!=second:raise RuntimeError('Two EEPROM reads disagree')
        u=USB();desc=u.configuration();parsed=parse_configuration(desc)
        ptr=int.from_bytes(d.read('ram',0xc002,2),'big')
        ram=d.read('ram',ptr,len(desc))
        ram_parsed=parse_configuration(ram)
        if ptr!=0xc03a or ram_parsed!=parsed:
            raise RuntimeError('Active RAM and EP0 color descriptors disagree')
        edid=source_edid()
        (out/'baseline-eeprom.bin').write_bytes(first)
        (out/'baseline-config.bin').write_bytes(desc)
        (out/'baseline-ram-config.bin').write_bytes(ram)
        (out/'baseline-source-edid.bin').write_bytes(edid)
        report={'silicon_id':'a7109a','eeprom_bytes':size,'eeprom_sha256':sha(first),
                'source_edid_sha256':sha(edid),'configuration_sha256':sha(desc),
                'active_ram_base':ptr,**parsed,'procamp_shadow':d.read('ram',0xc6a0,8).hex(),
                'ram_ep0_differences':[{'offset':i,'ram':a,'ep0':b} for i,(a,b) in enumerate(zip(ram,desc)) if a!=b],
                'f819':d.read('ram',0xf819,1).hex(),'raw_frames_saved':False}
        try:
            other=u.configuration(7);(out/'baseline-other-speed.bin').write_bytes(other)
            report['other_speed']=parse_configuration(other)
        except (RuntimeError,ValueError) as ex:report['other_speed_error']=str(ex)
        save(out/'snapshot.json',report);print(json.dumps(report),flush=True)
    finally:
        if u:u.close()
        d.close()

def prepare(out):
    image=(out/'baseline-eeprom.bin').read_bytes();edid=(out/'baseline-source-edid.bin').read_bytes()
    desc=(out/'baseline-config.bin').read_bytes();snapshot=json.loads((out/'snapshot.json').read_text())
    candidates=out/'candidates';candidates.mkdir(exist_ok=True)
    for name,kw in [('gamma24',{'gamma':2.4}),('gamma28',{'gamma':2.8}),('srgb',{'srgb':True})]:
        e=edit_edid(edid,**kw);(candidates/f'edid-{name}.bin').write_bytes(e)
        row=manifest(edid,e,kind='edid',persistent_flashing_approved=False)
        try:
            firmware=edid_eeprom_candidate(image,edid,e)
            (candidates/f'eeprom-edid-{name}.bin').write_bytes(firmware)
            row['firmware']=manifest(image,firmware)
        except ValueError as ex:row['persistent_candidate_error']=str(ex)
        save(candidates/f'edid-{name}.json',row)
    for name in ('bt709','bt470m','bt470bg','srgb'):
        row={'kind':'usb-transfer','name':name,'baseline_sha256':sha(image),'persistent_flashing_approved':False}
        try:
            row['uvc_value']=transfer_value(name,snapshot['bcdUVC'])
            firmware=transfer_eeprom_candidate(image,desc,snapshot['active_ram_base'],name)
            (candidates/f'eeprom-transfer-{name}.bin').write_bytes(firmware)
            row['firmware']=manifest(image,firmware)
        except ValueError as ex:row['persistent_candidate_error']=str(ex)
        save(candidates/f'transfer-{name}.json',row)
    print('Prepared candidates and exact byte manifests',flush=True)

def apply_edid(out,name):
    baseline_guard(out)
    original=(out/'baseline-source-edid.bin').read_bytes()
    target=original if name=='baseline' else (out/'candidates'/f'edid-{name}.bin').read_bytes()
    validate_edid(target)
    state=out/'volatile-edid-state.json'
    # Save recovery information before touching the qualified F819.0 aperture.
    save(state,{'target':name,'expected_source_sha256':sha(target),'restore_edid':'baseline-source-edid.bin','status':'applying'})
    d=Device();gate=None
    try:
        gate=d.read('ram',0xf819,1)[0]
        if gate & 1:raise RuntimeError('EDID aperture gate already open; refusing overlapping operation')
        d.exchange(0xb6,0xf819,gate|1)
        observed=d.read('ram',0xfb00,256)
        if observed not in (original,target) and name!='baseline':
            raise RuntimeError('Open EDID aperture differs from baseline/target; restore baseline first')
        try:
            for i,v in enumerate(target):
                if observed[i]!=v:d.exchange(0xb6,0xfb00+i,v)
            actual=d.read('ram',0xfb00,256)
            if actual!=target:raise RuntimeError('Volatile EDID aperture readback mismatch')
        except Exception:
            for i,v in enumerate(original):d.exchange(0xb6,0xfb00+i,v)
            if d.read('ram',0xfb00,256)!=original:raise RuntimeError('EDID restoration failed')
            raise
    finally:
        if gate is not None:d.exchange(0xb6,0xf819,gate)
        d.close()
    baseline_guard(out)
    save(state,{'target':name,'expected_source_sha256':sha(target),'restore_edid':'baseline-source-edid.bin','status':'awaiting-source-reconnect','aperture_readback_verified':True})
    print('Volatile EDID verified. HDMI reconnect needed; source-readback must match before capture.',flush=True)

def verify_edid(out,name):
    expected=(out/'baseline-source-edid.bin').read_bytes() if name=='baseline' else (out/'candidates'/f'edid-{name}.bin').read_bytes()
    actual=source_edid()
    report={'expected_sha256':sha(expected),'observed_sha256':sha(actual),'verified':actual==expected}
    save(out/f'source-edid-{name}.json',report)
    if actual!=expected:raise RuntimeError('macOS still reports a different EDID; do not capture this candidate')
    print(json.dumps(report),flush=True)

def apply_transfer(out,name,reset=False):
    baseline_guard(out)
    original=(out/'baseline-config.bin').read_bytes();snap=json.loads((out/'snapshot.json').read_text())
    value=transfer_value(name,snap['bcdUVC']);ptr=snap['active_ram_base']
    target=bytearray(original)
    for r in snap['colors']:target[r['offset']+4]=value
    d=Device();u=None;changed=False
    try:
        if int.from_bytes(d.read('ram',0xc002,2),'big')!=ptr:raise RuntimeError('Descriptor RAM pointer changed')
        current=d.read('ram',ptr,len(original))
        allowed={r['offset']+4 for r in snap['colors']}
        ram_baseline=(out/'baseline-ram-config.bin').read_bytes()
        if any(a!=b and i not in allowed for i,(a,b) in enumerate(zip(current,ram_baseline))):
            raise RuntimeError('Descriptor changes extend beyond transfer fields')
        save(out/'volatile-transfer-state.json',{'target':name,'addresses':[ptr+i for i in sorted(allowed)],'status':'applying'})
        for i in sorted(allowed):d.exchange(0xb6,ptr+i,target[i])
        changed=True
        ram_before=d.read('ram',ptr,len(original))
        u=USB();actual=u.configuration()
        ram_after=d.read('ram',ptr,len(original))
        if actual!=bytes(target):
            save(out/f'transfer-{name}-readback.json',{'target':name,'requested_value':value,
                 'ep0_verified_before_reset':False,'reset_requested':reset,'reset_performed':False,
                 'ram_transfer_before_request':[ram_before[r['offset']+4] for r in snap['colors']],
                 'ram_transfer_after_request':[ram_after[r['offset']+4] for r in snap['colors']],
                 'served_configuration':parse_configuration(actual),'status':'edit-not-served'})
            raise RuntimeError('EP0 descriptor did not expose requested transfer')
        report={'target':name,'ep0_verified_before_reset':True,'bcdUVC':snap['bcdUVC'],'value':value,'reset_requested':reset}
        if reset:
            d.close();u.reset();u.close();u=None;time.sleep(3)
            d=Device();u=USB();after=u.configuration()
            report['ep0_verified_after_reset']=after==bytes(target)
            report['after_reset']=parse_configuration(after)
            if after!=bytes(target):report['status']='reset-discarded-edit'
        save(out/f'transfer-{name}-readback.json',report);print(json.dumps(report),flush=True)
    except Exception:
        if changed:
            if not d.dev:d=Device()
            for r in snap['colors']:d.exchange(0xb6,ptr+r['offset']+4,r['transfer'])
            save(out/'volatile-transfer-state.json',{'target':name,'status':'restored-after-error'})
        raise
    finally:
        if u:u.close()
        d.close()

def restore_transfer(out):
    baseline_guard(out);d=Device();u=None
    try:
        desc=(out/'baseline-config.bin').read_bytes();snap=json.loads((out/'snapshot.json').read_text())
        for r in snap['colors']:d.exchange(0xb6,snap['active_ram_base']+r['offset']+4,r['transfer'])
        u=USB()
        if u.configuration()!=desc:raise RuntimeError('Baseline configuration not restored')
    finally:
        if u:u.close()
        d.close()
    print('Baseline transfer fields restored and verified',flush=True)
    save(out/'volatile-transfer-state.json',{'target':'baseline','status':'restored','ep0_verified':True})

def stats(cap):
    import numpy as np
    pattern=json.loads((PATTERN_DIR/'endpoint-pattern.json').read_text());result={}
    for index,name in enumerate(('Y','Cb','Cr')):
        x=np.array(pattern['bands'][name]['realized_rgb_to_ycbcr_full709'])[:,index]
        y=np.array(cap['bands'][index]['measured_'+name],dtype=float)
        coef=np.linalg.lstsq(np.column_stack((x,np.ones(len(x)))),y,rcond=None)[0]
        residual=y-(coef[0]*x+coef[1]);low,high=(0,255) if name=='Y' else (1,254)
        def count(seq,test):
            n=0
            for v in seq:
                if not test(v):break
                n+=1
            return n
        result[name]={'rmse':float(np.sqrt(np.mean(residual**2))),'span':float(y.max()-y.min()),
                      'minimum':float(y.min()),'maximum':float(y.max()),
                      'monotonic_decreases':int(np.sum(np.diff(y)<-1)),
                      'low_endpoint_plateau':count(y,lambda v:v==y[0]),
                      'high_endpoint_plateau':count(y[::-1],lambda v:v==y[-1]),
                      'extra_rail_samples':max(0,count(y,lambda v:v<=low)-1)+max(0,count(y[::-1],lambda v:v>=high)-1),
                      'slope':float(coef[0]),'intercept':float(coef[1])}
    return result

def capture(out,label,edid_name='baseline',transfer_name='bt709'):
    if not re.fullmatch('[a-zA-Z0-9_-]+',label):raise ValueError('Unsafe label')
    baseline_guard(out);verify_edid(out,edid_name)
    u=USB()
    try:
        active=u.configuration(); parsed=parse_configuration(active)
        expected=transfer_value(transfer_name,parsed['bcdUVC'])
        if any(r['transfer']!=expected for r in parsed['colors']):raise RuntimeError('Active transfer fields differ from requested condition')
    finally:u.close()
    destination=out/f'{label}-capture.json'
    if destination.exists():raise RuntimeError('Refusing to overwrite capture evidence')
    for attempt in range(3):
        scratch=out/f'{label}-attempt-{attempt+1}.json'
        cp=subprocess.run(['/private/tmp/transfer_capture',str(PATTERN_DIR/'endpoint-pattern.json'),str(scratch),*[str(SETTING[k]) for k in ('brightness','contrast','saturation')]],capture_output=True,text=True,timeout=145)
        save(out/f'{label}-attempt-{attempt+1}-process.json',{'returncode':cp.returncode,'stderr':cp.stderr})
        if not scratch.exists():continue
        cap=json.loads(scratch.read_text())
        valid=cp.returncode==0 and cap['error'] is None and cap['frames_captured']==2 and cap['repeat_stable_within_1_code'] and cap['procamp_restored']
        valid=valid and all(abs(v-128)<=1 for key in ('measured_Cb','measured_Cr') for v in cap['bands'][0][key])
        metrics=stats(cap)
        valid=valid and all(r['span']>150 and r['monotonic_decreases']==0 for r in metrics.values())
        # Active-state gates again after capture; firmware callbacks may rebuild RAM.
        verify_edid(out,edid_name);u=USB()
        try:valid=valid and u.configuration()==active
        finally:u.close()
        if valid:
            cap['qualification']={'edid':edid_name,'transfer':transfer_name,'attempt':attempt+1,'metrics':metrics,'procamp':SETTING}
            save(destination,cap);print(json.dumps(cap['qualification']),flush=True);return
        print(f'Rejected capture attempt {attempt+1}',flush=True)
    raise RuntimeError('Three capture attempts failed validation')

def native_metadata(out,label,edid_name='baseline',transfer_name='bt709'):
    """Native attachments are separate evidence; AVFoundation may convert range."""
    destination=out/f'{label}-native-metadata.json'
    if destination.exists():raise RuntimeError('Refusing to overwrite native evidence')
    def controls(args=()):
        cp=subprocess.run(['/private/tmp/transfer_controls',*map(str,args)],capture_output=True,text=True,check=True,timeout=15)
        return json.loads(cp.stdout)
    verify_edid(out,edid_name)
    u=USB()
    try:
        active=u.configuration();parsed=parse_configuration(active)
        if any(r['transfer']!=transfer_value(transfer_name,parsed['bcdUVC']) for r in parsed['colors']):
            raise RuntimeError('Native metadata condition transfer mismatch')
    finally:u.close()
    old=controls();old={k:old[k] for k in SETTING}
    try:
        if old['hue']!=0:raise RuntimeError('Nonzero initial hue; control helper cannot restore it')
        applied=controls(tuple(SETTING[k] for k in ("brightness","contrast","saturation")))
        if any(applied[k]!=v for k,v in SETTING.items()):raise RuntimeError('Native procamp application failed')
        app='/private/tmp/TransferMetadataProbe.app/Contents/MacOS/TransferMetadataProbe'
        helper=app if Path(app).exists() else '/private/tmp/transfer_native_metadata'
        args=[helper,str(PATTERN_DIR/'endpoint-pattern.json'),str(destination)]
        if os.geteuid()==0:
            if not Path(app).exists():raise RuntimeError('Build the camera-declared native app first')
            args=['/bin/launchctl','asuser',str(ROOT.stat().st_uid),'/usr/bin/open','-n','-a',str(Path(app).parents[2]),'--args',*args[1:]]
            cp=subprocess.run(args,capture_output=True,text=True,timeout=20)
            deadline=time.monotonic()+130
            while not destination.exists() and time.monotonic()<deadline:time.sleep(.25)
        else:
            cp=subprocess.run(args,capture_output=True,text=True,timeout=145)
        save(out/f'{label}-native-process.json',{'returncode':cp.returncode,'stderr':cp.stderr})
        after=controls()
        if not destination.exists():raise RuntimeError('Native capture produced no attachment record')
        result=json.loads(destination.read_text())
        attachments=result.get('color_metadata',{}).get('pixel_buffer_attachments',{})
        if 'icc_profile_base64' in attachments:
            profile=base64.b64decode(attachments['icc_profile_base64'])
            result['color_metadata']['icc_summary']=icc_summary(profile)
        result['procamp_before']=applied;result['procamp_after']=after
        result['qualification_condition']={'edid':edid_name,'transfer':transfer_name}
        result['procamp_controlled']=all(after[k]==v for k,v in SETTING.items())
        result['valid_for_metadata']=cp.returncode==0 and result['error'] is None and result['frames_captured']==2 and result['procamp_controlled']
        save(destination,result)
        if not result['valid_for_metadata']:raise RuntimeError('Native metadata capture was not valid')
        verify_edid(out,edid_name);u=USB()
        try:
            if u.configuration()!=active:raise RuntimeError('Descriptor changed during native capture')
        finally:u.close()
        print(json.dumps(result['color_metadata']),flush=True)
    finally:
        restored=controls((old['brightness'],old['contrast'],old['saturation']))
        if any(restored[k]!=old[k] for k in SETTING):raise RuntimeError('Native procamp restore failed')

def icc_summary(profile):
    """Decode TRC tag types and parameters, without interpreting them as wire proof."""
    if len(profile)<132 or profile[36:40]!=b'acsp':raise ValueError('Malformed ICC profile')
    count=int.from_bytes(profile[128:132],'big');tags={}
    if 132+count*12>len(profile):raise ValueError('Truncated ICC tag directory')
    for i in range(count):
        row=profile[132+12*i:144+12*i];name=row[:4].decode('ascii',errors='replace')
        offset=int.from_bytes(row[4:8],'big');length=int.from_bytes(row[8:12],'big')
        if offset+length>len(profile):raise ValueError('ICC tag outside profile')
        b=profile[offset:offset+length]
        if name not in ('rTRC','gTRC','bTRC','kTRC'):continue
        entry={'type':b[:4].decode('ascii',errors='replace')}
        if b[:4]==b'curv' and len(b)>=12:
            n=int.from_bytes(b[8:12],'big');entry['entries']=n
            if n==1 and len(b)>=14:entry['gamma']=int.from_bytes(b[12:14],'big')/256
        elif b[:4]==b'para' and len(b)>=12:
            entry['function_type']=int.from_bytes(b[8:10],'big')
            entry['parameters']=[int.from_bytes(b[j:j+4],'big',signed=True)/65536 for j in range(12,len(b)-3,4)]
        tags[name]=entry
    return {'sha256':sha(profile),'bytes':len(profile),'trc_tags':tags,
            'limitation':'Host ICC interpretation; not proof of source HDMI encoding or MS2109 transfer processing'}

def report(out):
    """Compare accepted captures to A1; A2 is required before any promotion."""
    captures={p.stem.removesuffix('-capture'):json.loads(p.read_text()) for p in out.glob('*-capture.json')}
    if 'baseline' not in captures:raise RuntimeError('No accepted baseline capture')
    reference=captures['baseline']['qualification']['metrics']; rows=[]
    a2=captures.get('baseline-repeat')
    repeat_ok=False
    if a2:
        repeat_ok=all(max(abs(a-b) for a,b in zip(captures['baseline']['bands'][i]['measured_'+ch],a2['bands'][i]['measured_'+ch]))<=1 for i,ch in enumerate(('Y','Cb','Cr')))
    for label,cap in captures.items():
        m=cap['qualification']['metrics']
        checks={'luma_error_halved':m['Y']['rmse'] <= .5*reference['Y']['rmse'],
                'chroma_error_not_worse':all(m[c]['rmse'] <= reference[c]['rmse'] for c in ('Cb','Cr')),
                'coverage_preserved':all(m[c]['span'] >= reference[c]['span']-2 for c in ('Y','Cb','Cr')),
                'no_new_clipping':all(m[c]['extra_rail_samples'] <= reference[c]['extra_rail_samples'] for c in ('Y','Cb','Cr')),
                'monotonic':all(m[c]['monotonic_decreases']==0 for c in ('Y','Cb','Cr')),
                'baseline_repeat_stable':repeat_ok}
        rows.append({'label':label,'metrics':m,'checks':checks,'accepted':all(checks.values())})
    result={'baseline':reference,'conditions':rows,'raw_frames_saved':False,
            'conclusion':'Qualified candidate exists' if any(r['accepted'] for r in rows) else 'No qualified correction; unmeasured conditions are not failures',
            'baseline_repeat_present':a2 is not None}
    save(out/'qualification-report.json',result)
    # Standalone SVG compares primary waveforms and straight-line residuals.
    import html
    import numpy as np
    pattern=json.loads((PATTERN_DIR/'endpoint-pattern.json').read_text())
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="730">','<rect width="1200" height="730" fill="white"/>','<style>text{font:14px sans-serif}</style>','<text x="35" y="25">Raw YUY2 metadata qualification — waveforms and affine residuals</text>']
    colors=['#111111','#cf442f','#1769aa','#27864b','#9d4aab','#95652a']
    for i,ch in enumerate(('Y','Cb','Cr')):
        x0=40+395*i;parts.append(f'<text x="{x0}" y="65">{ch}</text>')
        x=np.array(pattern['bands'][ch]['realized_rgb_to_ycbcr_full709'])[:,i]
        for residual,top,height in ((False,85,265),(True,400,180)):
            parts.append(f'<rect x="{x0}" y="{top}" width="345" height="{height}" fill="none" stroke="#aaa"/>')
            if residual:parts.append(f'<path d="M{x0} {top+height/2}h345" stroke="#ddd"/>')
            for j,(label,cap) in enumerate(captures.items()):
                y=np.array(cap['bands'][i]['measured_'+ch],dtype=float)
                if residual:
                    coef=np.linalg.lstsq(np.column_stack((x,np.ones(len(x)))),y,rcond=None)[0];y=y-(coef[0]*x+coef[1])
                lo,hi=(-16,16) if residual else (0,255)
                points=' '.join(f'{x0+(xx-x.min())/(x.max()-x.min())*345:.2f},{top+height-(yy-lo)/(hi-lo)*height:.2f}' for xx,yy in zip(x,y))
                parts.append(f'<polyline points="{points}" fill="none" stroke="{colors[j%len(colors)]}" stroke-width="1.5"/>')
    for j,label in enumerate(captures):parts.append(f'<text x="35" y="{625+j*20}" fill="{colors[j%len(colors)]}">{html.escape(label)}</text>')
    parts.append('</svg>');(out/'qualification-waveforms.svg').write_text('\n'.join(parts))
    print(json.dumps(result),flush=True)

def suite(out):
    """One administrator session; physical reconnect gates never imply consent."""
    state=out/'suite-state.json'
    def phase(status,**details):
        save(state,{'status':status,**details});print(json.dumps({'status':status,**details}),flush=True)
    def wait_edid(name):
        expected=(out/'baseline-source-edid.bin').read_bytes() if name=='baseline' else (out/'candidates'/f'edid-{name}.bin').read_bytes()
        phase('awaiting-hdmi-reconnect',edid=name,expected_sha256=sha(expected))
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            try:
                if source_edid()==expected:
                    time.sleep(2);verify_edid(out,name);return
            except (RuntimeError,subprocess.SubprocessError):pass
            time.sleep(.5)
        raise RuntimeError('Source EDID reconnect gate timed out')
    def native(label,edid='baseline',transfer='bt709'):
        phase('native-metadata',label=label)
        try:native_metadata(out,label,edid,transfer)
        except Exception as ex:
            save(out/f'{label}-native-error.json',{'error':str(ex),'raw_capture_unaffected':True})
            print(f'Native metadata limitation: {ex}',flush=True)
    try:
        baseline_guard(out)
        if not (out/'baseline-capture.json').exists():
            wait_edid('baseline');capture(out,'baseline')
        # Resume skips measured candidates, but every new EDID starts from baseline.
        for name in ('gamma24','gamma28','srgb'):
            measured=(out/f'{name}-capture.json').exists()
            if measured and (out/f'{name}-native-metadata.json').exists():continue
            expected=(out/'candidates'/f'edid-{name}.bin').read_bytes()
            if source_edid()!=expected:
                if source_edid()!=(out/'baseline-source-edid.bin').read_bytes():
                    apply_edid(out,'baseline');wait_edid('baseline')
                apply_edid(out,name);wait_edid(name)
            if not measured:
                phase('raw-capture',edid=name);capture(out,name,name)
            native(name,name)
            apply_edid(out,'baseline');wait_edid('baseline')
        wait_edid('baseline')
        for name in ('bt470m','bt470bg'):
            if (out/f'{name}-capture.json').exists() or (out/f'{name}-probe-error.json').exists():continue
            phase('usb-transfer-probe',transfer=name)
            try:
                apply_transfer(out,name,reset=True)
                readback=json.loads((out/f'transfer-{name}-readback.json').read_text())
                if not readback.get('ep0_verified_after_reset'):
                    print(f'{name}: reset discarded edit; persistent candidate awaits separate approval',flush=True)
                    continue
                wait_edid('baseline');capture(out,name,'baseline',name);native(name,'baseline',name)
            except Exception as ex:
                save(out/f'{name}-probe-error.json',{'error':str(ex),'measured':False})
            finally:restore_transfer(out)
        if not (out/'baseline-repeat-capture.json').exists():capture(out,'baseline-repeat')
        if not (out/'baseline-native-metadata.json').exists():native('baseline')
        report(out);baseline_guard(out);phase('complete',persistent_writes=False)
    except Exception as ex:
        phase('failed',error=str(ex))
        # Restore the volatile metadata; source refresh may still need HDMI reconnect.
        try:apply_edid(out,'baseline');restore_transfer(out)
        except Exception as restore_error:
            save(out/'suite-restore-error.json',{'error':str(restore_error),'recovery':'USB power cycle reloads unchanged EEPROM'})
        raise
    finally:
        if os.geteuid()==0:
            owner=ROOT.stat()
            for path in out.rglob('*'):os.chown(path,owner.st_uid,owner.st_gid)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['snapshot','prepare','apply-edid','verify-edid','apply-transfer','restore-transfer','capture','native-metadata','report','suite'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--name',default='baseline')
    p.add_argument('--label',default='baseline');p.add_argument('--edid',default='baseline')
    p.add_argument('--transfer',default='bt709');p.add_argument('--reset',action='store_true')
    a=p.parse_args();out=a.output.resolve()
    if a.command=='snapshot':snapshot(out)
    elif a.command=='prepare':prepare(out)
    elif a.command=='apply-edid':apply_edid(out,a.name)
    elif a.command=='verify-edid':verify_edid(out,a.name)
    elif a.command=='apply-transfer':apply_transfer(out,a.name,a.reset)
    elif a.command=='restore-transfer':restore_transfer(out)
    elif a.command=='report':report(out)
    elif a.command=='suite':suite(out)
    elif a.command=='native-metadata':native_metadata(out,a.label,a.edid,a.transfer)
    else:capture(out,a.label,a.edid,a.transfer)

if __name__=='__main__':main()
