"""Measure RMS gaps, dominant tones and L/R lag in a stereo S16 WAV."""
import argparse, hashlib, json, wave
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser(); p.add_argument('input',type=Path); p.add_argument('--output',type=Path)
a=p.parse_args()
with wave.open(str(a.input),'rb') as w:
    rate=w.getframerate()
    if w.getnchannels()!=2 or w.getsampwidth()!=2:
        raise ValueError('Expected stereo 16-bit PCM')
    samples=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').reshape(-1,2).astype(float)
window=rate//20
blocks=samples[:len(samples)//window*window].reshape(-1,window,2)
rms=np.sqrt(np.mean(blocks**2,axis=1))
result={'sha256':hashlib.sha256(a.input.read_bytes()).hexdigest(),'rate':rate,'frames':len(samples),'pcm_duration_s':len(samples)/rate,'window_ms':50,'channels':[]}
for channel in range(2):
    v=samples[:,channel]; spec=np.abs(np.fft.rfft((v-v.mean())*np.hanning(len(v))))
    top=np.argsort(spec[1:])[-5:]+1
    peak_rms=float(rms[:,channel].max())
    result['channels'].append({'index':channel,'peak':float(np.abs(v).max()),'rms_min':float(rms[:,channel].min()),'rms_median':float(np.median(rms[:,channel])),'rms_max':peak_rms,'silent_window_fraction':float(np.mean(rms[:,channel]<max(1,peak_rms*.01))),'dominant_hz':[float(k*rate/len(v)) for k in top[::-1]],'window_rms':rms[:,channel].tolist()})
active=np.all(rms>np.max(rms,axis=0)*.2,axis=1)
# Exclude block edges, and measure correlation only while both tones are on.
indices=np.concatenate([np.arange(i*window+32,(i+1)*window-32) for i in np.flatnonzero(active)]) if active.any() else np.array([],dtype=int)
result['lag_correlations']=[]
for lag in range(-4,5):
    valid=indices[(indices+lag>=0)&(indices+lag<len(samples))]
    if len(valid):
        x=samples[valid,0]; y=samples[valid+lag,1]
        corr=float(np.corrcoef(x,y)[0,1]) if x.std() and y.std() else None
    else: corr=None
    result['lag_correlations'].append({'lag_samples':lag,'correlation_ch0_n_ch1_n_plus_lag':corr})
if a.output:a.output.write_text(json.dumps(result,indent=2)+'\n')
for c in result['channels']:
    print({k:v for k,v in c.items() if k!='window_rms'})
print('Lag correlation:', result['lag_correlations'])
print('Duration of PCM:',result['pcm_duration_s'])
