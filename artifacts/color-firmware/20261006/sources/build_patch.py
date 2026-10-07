"""Offline, checksum-validated neutral/calibrated MS2109 startup profiles."""
from pathlib import Path
import argparse
import hashlib
import json

ORIGINAL_SHA = '37103dccfc6c5e2062b6d22a0a619729449427270e52ae4332fde0da0f49dfe1'
ROM_SHA = 'b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8'
CALIBRATED = {'brightness_signed': -18, 'brightness_ui': 110,
              'contrast': 149, 'saturation': 147, 'hue': 0}
COLOR_RECORDS = (0xc2a4, 0xc43b)

def validate(b):
    if len(b) not in (2048, 4096) or b[:2] not in (b'\xa5\x5a', b'\x96\x69'):
        raise ValueError('Unknown EEPROM layout')
    n = int.from_bytes(b[2:4], 'big')
    if not 5 <= n <= len(b)-52:
        raise ValueError('Invalid code length')
    for start, end, check in ((2,48,48+n), (48,48+n,50+n)):
        if sum(b[start:end]) & 65535 != int.from_bytes(b[check:check+2], 'big'):
            raise ValueError('EEPROM checksum mismatch')
    return n

def stores(addr, values):
    out = bytearray([0x90, addr >> 8, addr & 255])
    for i, v in enumerate(values):
        if i:
            out.append(0xa3)
        out.extend((0x74,v,0xf0))
    return out

def matrix_patch():
    """Only change a recognized color descriptor, never adjacent frame bytes.

    Stage 1 corrects declarations before USB interrupts are enabled. Stage 2
    repairs them if configuration RAM is rebuilt. Preserve primaries/transfer.
    Other-speed descriptors served directly from mask ROM are outside this
    qualified high-speed RAM patch.
    """
    output = bytearray()
    for addr in COLOR_RECORDS:
        block = bytearray([0x90, addr >> 8, addr & 255])
        branches = []
        for i, value in enumerate(bytes.fromhex('06 24 0d 01 01 04')):
            if i: block.append(0xa3)  # INC DPTR
            block.extend((0xe0, 0xb4, value, 0))  # MOVX A,@DPTR; CJNE A,#value,end
            branches.append(len(block)-1)
        block.extend((0x74, 1, 0xf0))  # DPTR still points to bMatrixCoefficients
        for branch in branches:
            block[branch] = len(block)-(branch+1)
        output.extend(block)
    return bytes(output)


def build(b, channel_order=False, calibrated_color=False, rom=None):
    n = validate(b)
    if hashlib.sha256(b).hexdigest() != ORIGINAL_SHA:
        raise ValueError('This patch is qualified only for the backed-up connected dongle')
    if b[48] != 0x90 or b[51:53] != b'\xef\xf0' or not b[4] & 1:
        raise ValueError('Unexpected Patch_Common hook')
    # Stage 1 occurs after ROM 4d54 initializes current state + hardware.
    if calibrated_color:
        if rom is None or hashlib.sha256(rom).hexdigest() != ROM_SHA:
            raise ValueError('Calibrated descriptor offsets require the qualified MS2109 ROM')
        for addr in COLOR_RECORDS:
            if rom[addr:addr+6] != bytes.fromhex('06 24 0d 01 01 04'):
                raise ValueError('Unexpected saved color descriptor')
        # Signed UVC brightness is a little-endian int16, hardware is signed8.
        procamp = stores(0xc6a0, [0xee,0xff,149,0,0,0,147,0])
        procamp += stores(0xfe90, [0xee,149,147,0])
        procamp += matrix_patch()
    else:
        procamp = stores(0xc6a0, [0,0,128,0,0,0,128,0])
        procamp += stores(0xfe90, [0,128,128,0])
    # Stage 2: exact same descriptor fields as the specified upstream patch.
    stereo = stores(0xc4c5, [2]) + stores(0xc4c9, [0x80,0xbb,0])
    # Qualified with the Mac HDMI source: FE60=01 routes continuous source L
    # to USB L and gapped source R to USB R. This does not correct sample skew.
    if channel_order:
        stereo += stores(0xfe60, [1])
    if calibrated_color:
        stereo += matrix_patch()
    # CJNE uses SIGNED relative displacement; a 128..255-byte block would
    # silently branch backward. Use a forward LJMP for larger stage bodies.
    def stage(number, body, start):
        if len(body) <= 127:
            return bytes([0xef,0xb4,number,len(body)]) + body
        target = start+9+len(body)
        return bytes([0xef,0xb4,number,2,0x80,3,0x02,target>>8,target&255]) + body
    dest = 0xcc00+n+4
    patch = bytearray(stage(1,procamp,dest))
    patch += stage(2,stereo,dest+len(patch))
    patch += b[48:51] + b'\x22'  # displaced MOV DPTR, then RET
    # Preserve old checksums as upstream does; append only into erased EEPROM.
    off = 48+n+4
    if off+len(patch)+4 > len(b) or any(v != 255 for v in b[off:off+len(patch)+4]):
        raise ValueError('Insufficient erased space for patch')
    out = bytearray(b)
    out[off:off+len(patch)] = patch
    out[48:51] = bytes([0x12,dest>>8,dest&255])
    new_n = n+4+len(patch)
    out[2:4] = new_n.to_bytes(2,'big')
    out[48+new_n:50+new_n] = (sum(out[2:48]) & 65535).to_bytes(2,'big')
    out[50+new_n:52+new_n] = (sum(out[48:48+new_n]) & 65535).to_bytes(2,'big')
    validate(out)
    return bytes(out), bytes(patch), dest

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('original',type=Path); p.add_argument('output',type=Path)
    p.add_argument('--channel-order',action='store_true')
    p.add_argument('--calibrated-color',action='store_true',help='Measured full-span UI B/C/S 110/149/147, hue 0, BT.709 matrix declarations')
    p.add_argument('--rom',type=Path,help='Qualified saved mask ROM (required with --calibrated-color)')
    a=p.parse_args()
    if a.calibrated_color and not a.rom:p.error('--calibrated-color requires --rom')
    if a.output.exists() or a.output.with_suffix('.hook.bin').exists() or a.output.with_suffix('.json').exists():p.error('Use a new output filename; existing images are preserved')
    original=a.original.read_bytes(); out, patch, dest=build(original,a.channel_order,a.calibrated_color,a.rom.read_bytes() if a.rom else None)
    a.output.write_bytes(out)
    a.output.with_suffix('.hook.bin').write_bytes(patch)
    changes=[{'offset':i,'old':v,'new':out[i]} for i,v in enumerate(original) if v!=out[i]]
    metadata={'original_sha256':hashlib.sha256(original).hexdigest(),'patched_sha256':hashlib.sha256(out).hexdigest(),'hook_address':hex(dest),'hook_bytes':len(patch),'code_size':validate(out),'changes':changes,'channel_order':a.channel_order,'profile':'calibrated BT.709 full-span' if a.calibrated_color else 'neutral limited baseline'}
    if a.calibrated_color:
        metadata.update({'controls':CALIBRATED,'color_matching':{'primaries':1,'transfer':1,'matrix':1,'ram_records':[hex(addr) for addr in COLOR_RECORDS],'quantization_range':'No UVC descriptor field; measured full-range target','other_speed_mask_rom':'unchanged'},'get_def':'Unchanged ROM constants: signed brightness -11, contrast 148, hue 0, saturation 180','rom_sha256':hashlib.sha256(a.rom.read_bytes()).hexdigest(),'calibration_result':'artifacts/color-probe/20261006-auto-calibration-v2/result.json'})
    a.output.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(f'{len(changes)} changed bytes; hook {dest:04x}, {len(patch)} bytes; SHA256 {hashlib.sha256(out).hexdigest()}')
