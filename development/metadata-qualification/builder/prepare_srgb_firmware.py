"""Prepare a provisional sRGB/D65 candidate from a qualified EEPROM baseline."""
import argparse
import json
from pathlib import Path
from transfer_metadata import edit_edid, edid_eeprom_candidate, manifest, validate
from control_assembler import compact_stores

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--baseline',required=True,type=Path)
p.add_argument('--source-edid',required=True,type=Path)
p.add_argument('--output',required=True,type=Path)
p.add_argument('--procamp',nargs=3,type=int,metavar=('BRIGHTNESS','CONTRAST','SATURATION'))
a=p.parse_args()
metadata=a.output.with_suffix('.json')
if a.output.exists() or metadata.exists():p.error('Output or manifest exists')
baseline=a.baseline.read_bytes(); edid=a.source_edid.read_bytes()
profile=edit_edid(edid,srgb=True)
image=edid_eeprom_candidate(baseline,edid,profile)
n=validate(image)
if a.procamp:
    brightness,contrast,saturation=a.procamp
    if not -128<=brightness<=127 or not 0<=contrast<=255 or not 0<=saturation<=255:
        p.error('Procamp values outside qualified byte ranges')
    data=bytearray(image)
    replacements=[(0xc6a0,[0xee,0xff,149,0,0,0,147,0],[brightness&255,255 if brightness<0 else 0,contrast,0,0,0,saturation,0]),(0xfe90,[0xee,149,147,0],[brightness&255,contrast,saturation,0])]
    for addr,old,new in replacements:
        before=compact_stores(addr,old);after=compact_stores(addr,new)
        if image.count(before)!=1 or len(before)!=len(after):raise ValueError('Require unique, same-length qualified startup routine')
        pos=image.index(before);data[pos:pos+len(before)]=after
    data[50+n:52+n]=(sum(data[48:48+n])&65535).to_bytes(2,'big')
    image=bytes(data);validate(image)

a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_bytes(image)
metadata.write_text(json.dumps(manifest(baseline,image,status='provisional chroma improvement; not a validated luma correction',baseline_path=str(a.baseline.resolve()),source_edid_path=str(a.source_edid.resolve()),overlay_bytes=n,remaining_code_bytes=1996-n,startup_procamp=a.procamp or 'unchanged from qualified baseline',preservation='existing hooks, names, audio fixes, UVC metadata, timings and transport retained',qualification='RAM EDID source-readback verified; persistent sRGB candidate not flashed',recalibration_required=True),indent=2)+'\n')
print(a.output.resolve())
