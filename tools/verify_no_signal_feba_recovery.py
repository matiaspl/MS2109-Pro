#!/usr/bin/env python3
"""Read-only check of FEBA and source video after the reversible no-signal sweep."""
import hashlib
import json
import subprocess
from pathlib import Path
from ms2109_hid import Device

out = Path('artifacts/no-signal-feba/hdmi-recovered')
out.mkdir(parents=True, exist_ok=False)
d = Device()
try:
    d.identify_eeprom()
    eeprom = d.read('eeprom', 0, d.eeprom_size)
    status = {'feba': d.read('ram', 0xfeba, 1)[0], 'f92c': d.read('ram', 0xf92c, 1)[0],
              'eeprom_sha256': hashlib.sha256(eeprom).hexdigest()}
finally:
    d.close()
with (out / 'capture.log').open('w') as log:
    subprocess.run(['ffmpeg','-nostdin','-hide_banner','-f','avfoundation','-framerate','5',
                    '-video_size','1920x1080','-pixel_format','yuyv422','-i','usb video:none',
                    '-t','3','-an','-frames:v','1','-update','1',str(out/'hdmi-recovered.png')],
                   stdout=log,stderr=log,check=True,timeout=15)
from PIL import Image
im=Image.open(out/'hdmi-recovered.png').convert('RGB')
status.update({'image_size': im.size, 'image_colors_sampled': len(set(im.resize((100,56)).getdata())),
               'image_sha256': hashlib.sha256((out/'hdmi-recovered.png').read_bytes()).hexdigest()})
if status['feba'] != 0:
    raise RuntimeError(f"FEBA not restored to 00: {status['feba']:02x}")
if status['image_colors_sampled'] <= 1:
    raise RuntimeError('Captured source frame is uniform; recovery is not verified')
(out/'status.json').write_text(json.dumps(status,indent=2)+'\n')
print(json.dumps(status,indent=2))
