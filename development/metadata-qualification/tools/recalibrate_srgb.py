"""Reversible raw YUY2 procamp sweep under source-verified sRGB EDID."""
import json,os,subprocess,time
from pathlib import Path
import qualify_transfer_metadata as q
OUT=q.ROOT/'artifacts/srgb-d65-firmware-20261012/recalibration'
RUN=q.ROOT/'artifacts/transfer-metadata-20261012'
OUT.mkdir(exist_ok=True);os.chown(OUT,501,20)
rows=[]
def controls(v=None):
 args=[] if v is None else [str(v[k]) for k in ('brightness','contrast','saturation')]
 return json.loads(subprocess.check_output(['/private/tmp/transfer_controls',*args],text=True,timeout=20))
def measure(setting,label):
 q.verify_edid(RUN,'srgb');u=q.USB()
 try:
  active=u.configuration();assert all(r['transfer']==1 for r in q.parse_configuration(active)['colors'])
 finally:u.close()
 for attempt in range(1,4):
  dest=OUT/f'{label}-attempt-{attempt}.json'
  cp=subprocess.run(['/private/tmp/transfer_capture',str(q.PATTERN_DIR/'endpoint-pattern.json'),str(dest),*[str(setting[k]) for k in ('brightness','contrast','saturation')]],capture_output=True,text=True,timeout=145)
  q.save(OUT/f'{label}-attempt-{attempt}-process.json',{'returncode':cp.returncode,'stderr':cp.stderr})
  if not dest.exists():continue
  cap=json.loads(dest.read_text()); valid=cp.returncode==0 and cap['error'] is None and cap['frames_captured']==2 and cap['repeat_stable_within_1_code'] and cap['procamp_restored']
  metrics=q.stats(cap);valid=valid and all(r['span']>150 and r['monotonic_decreases']==0 for r in metrics.values()) and all(abs(x-128)<=1 for k in ('measured_Cb','measured_Cr') for x in cap['bands'][0][k])
  q.verify_edid(RUN,'srgb');u=q.USB()
  try:valid=valid and u.configuration()==active
  finally:u.close()
  if valid:
   row={'label':label,'procamp':dict(setting),'metrics':metrics,'capture':cap}; rows.append(row);q.save(OUT/'progress.json',rows); print(json.dumps({'label':label,'procamp':setting,'metrics':metrics}),flush=True);return row
  print('Invalid capture '+label+' attempt '+str(attempt),flush=True)
 raise RuntimeError('Three invalid capture attempts: '+label)
def stage(key,values,current):
 candidates=[]
 for value in values:
  s=dict(current);s[key]=value;candidates.append(measure(s,key+'-'+str(value)))
 channels=('Cb','Cr') if key=='saturation' else ('Y',)
 safe=[r for r in candidates if all(r['metrics'][c]['extra_rail_samples']==0 for c in channels)]
 if not safe:raise RuntimeError('No unclipped candidate: '+key)
 if key=='brightness':winner=min(safe,key=lambda r:(abs((r['metrics']['Y']['minimum']+r['metrics']['Y']['maximum'])/2-127.5),-r['metrics']['Y']['span']))
 else:winner=max(safe,key=lambda r:(min(r['metrics'][c]['span'] for c in channels),-sum(r['metrics'][c]['rmse'] for c in channels)))
 current[key]=winner['procamp'][key];print('SELECTED '+key+' '+str(current[key]),flush=True)
q.baseline_guard(RUN);q.verify_edid(RUN,'srgb');original=controls();current={'brightness':-17,'contrast':148,'hue':0,'saturation':147}
try:
 initial=measure(current,'starting-srgb')
 stage('brightness',[-19,-18,-17,-16,-15],current)
 stage('contrast',[144,146,147,148,149,150],current)
 b=current['brightness'];stage('brightness',range(b-1,b+2),current)
 stage('saturation',[138,140,142,144,146,147,148,149,150],current)
 final=measure(current,'selected-repeat-1');second=measure(current,'selected-repeat-2')
 assert final['capture']['bands']==second['capture']['bands'],'Final repeat differs'
 q.save(OUT/'result.json',{'selected_procamp':current,'starting_procamp':original,'initial':initial,'final':final,'second':second,'raw_frames_saved':False,'runtime_restored':True,'persistent_writes':False})
finally:
 restored=controls(original);assert all(restored[k]==original[k] for k in ('brightness','contrast','hue','saturation'))
 for path in OUT.rglob('*'):os.chown(path,501,20)
