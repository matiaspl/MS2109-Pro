"""Correct the measured MS2109 half-frame rotation in an S16 stereo WAV.

Use only on the uncorrected path identified with continuous-left/gapped-right
signals. Drops one initial 16-bit word, repairing swap + relative sample offset.
"""
import argparse
from pathlib import Path
import wave
from align_pcm import Aligner

def correct(source, target):
    if target.exists():
        raise ValueError('Refusing to overwrite output')
    with wave.open(str(source),'rb') as src:
        if src.getnchannels()!=2 or src.getsampwidth()!=2 or src.getframerate()!=48000:
            raise ValueError('Expected 48 kHz stereo S16 PCM')
        params=src.getparams()
        with wave.open(str(target),'wb') as dst:
            dst.setparams(params)
            aligner=Aligner()
            while chunk:=src.readframes(16384):
                dst.writeframesraw(aligner.feed(chunk))
            aligner.finish()

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('source',type=Path); p.add_argument('target',type=Path)
    a=p.parse_args(); correct(a.source,a.target)
