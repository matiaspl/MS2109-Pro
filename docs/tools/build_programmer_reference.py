#!/usr/bin/env python3
"""Reproduce MS2109 reference evidence offline; never imports device transport.

The candidate index is a BYTE PATTERN index, not a disassembler or a claim of
reachable code. Reviewed assertions are separately pinned by signatures/hash.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from build_patch import validate

ROOT = Path(__file__).resolve().parents[1]
ROM_SHA = 'b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8'
EEPROM_SHA = '37103dccfc6c5e2062b6d22a0a619729449427270e52ae4332fde0da0f49dfe1'
SIGNATURES = [
 ('reset vector',0x0000,'024149'),
 ('normal hook gate',0x6ef8,'90cbd4e030e003126fac22'),
 ('normal hook stage mirror',0x6fac,'90c584eff012cc0022'),
 ('USB control replacement',0x4788,'90cbd4e030e10512cc108003122ad0c21322'),
 ('USB IRQ extension',0x2cb3,'90cbd4e030e20312cc20'),
 ('vector 000B replacement',0x5254,'90cbd4e030e30512cc30800f'),
 ('vector 0013 replacement',0x560c,'90cbd4e030e40512cc408008'),
 ('vector 0023 replacement',0x5813,'90cbd4e030e50512cc508003123269'),
 ('boot stage 0',0x31a5,'120016125f191269b0e4ff126ef8'),
 ('boot stage 1',0x31ef,'125884124d547f01126ef8'),
 ('loop stage 2',0x324e,'7f02126ef8'),
 ('header clear disables hooks',0x6844,'e490cbd4f0a3f022'),
 ('load size bound',0x34de,'d394fcee9413507a'),
 ('load includes header and checksums',0x34e6,'90c553e02434f090c552e03400f090c55474cbf0a374d0f0'),
 ('header checksum failure',0x2973,'90c7887402f0c322'),
 ('code checksum failure / success',0x29d9,'90c7887403f0c322d322'),
 ('XDATA read helper',0x700a,'8f828e83e0ff22'),
 ('XDATA write helper',0x7011,'8f828e83edf022'),
 ('masked write helper',0x65cd,'90c5b2eef0a3eff012700aac07edf45cfceb5d4cfc90c5b2e0fea3e0ffad04027011'),
 ('set bits helper',0x7018,'ac05ab040265cd'),
 ('rate argument save and F809 bit7',0x3e78,'90c56812087e7d807f097ef8127018'),
 ('rate equality branch',0x3ed5,'90c56c12086690c568121df77009'),
 ('rate equality sets bit3',0x3ee3,'7d087f617efe027018'),
 ('rate inequality sets bit0 clears bit3',0x3eec,'7d017f617efe1270187d087f617efe12000e22'),
 ('EDID aperture copy setup',0x6354,'90c54e1208c77d007c017f007efb125038'),
]
# Explicit function starts avoid the alignment errors in a whole-file linear sweep.
EXCERPTS = [(0x4149,8),(0x4190,12),(0x31a5,76),(0x5f19,24),
 (0x682e,20),(0x34a6,125),(0x28f5,146),(0x5e11,35),
 (0x6ef8,5),(0x6fac,5),(0x4788,8),(0x2cb3,25),
 (0x5237,40),(0x55ef,36),(0x57f6,36),(0x65cd,25),
 (0x700a,12),(0x4d54,65),(0x67f1,16),
 (0x3e78,64),(0x0866,18),(0x1e5a,6),(0x080f,24),
 (0x6345,17),(0x5038,48),(0x0492,29),(0x08c7,5),(0x08e7,6),
 (0x67d2,2),(0x67dc,5),(0x4cc7,2),(0x4cd1,3),(0x56ff,2),(0x5709,3)]

def hx(n): return f'0x{n:04X}'

def decode_rom_edid(rom):
    """Decode the pinned default ROM EDID without treating it as live state."""
    offset = 0x7738
    edid = rom[offset:offset + 256]
    if len(edid) != 256 or edid[:8] != bytes.fromhex('00ffffffffffff00'):
        raise ValueError('Default ROM EDID signature or size changed')
    if any(sum(edid[start:start + 128]) & 0xff for start in (0, 128)):
        raise ValueError('Default ROM EDID block checksum failed')
    dtd = edid[54:72]
    clock_hz = int.from_bytes(dtd[:2], 'little') * 10000
    h_active = dtd[2] | ((dtd[4] & 0xf0) << 4)
    h_blank = dtd[3] | ((dtd[4] & 0x0f) << 8)
    v_active = dtd[5] | ((dtd[7] & 0xf0) << 4)
    v_blank = dtd[6] | ((dtd[7] & 0x0f) << 8)
    h_total, v_total = h_active + h_blank, v_active + v_blank
    ext = edid[128:256]
    if ext[0] != 0x02 or ext[2] < 4 or ext[2] > 127:
        raise ValueError('Default ROM EDID CTA extension header changed')
    vics = []
    pos = 4
    while pos < ext[2]:
        header = ext[pos]
        tag, length = header >> 5, header & 0x1f
        pos += 1
        data = ext[pos:pos + length]
        if len(data) != length:
            raise ValueError('Default ROM EDID CTA data block is truncated')
        if tag == 2:
            vics.extend(value & 0x7f for value in data)
        pos += length
    return {
        'code_address': hx(offset),
        'size': len(edid),
        'checksums_valid': True,
        'base_detailed_timing': {
            'pixel_clock_hz': clock_hz,
            'active_pixels': [h_active, v_active],
            'total_pixels': [h_total, v_total],
            'refresh_hz': round(clock_hz / (h_total * v_total), 6),
        },
        'cta_video_identification_codes': vics,
        'interpretation_limit': 'Pinned ROM default EDID only; a board EEPROM may provide a custom active EDID.',
    }

def build(out, disassemble=False):
    rompath = ROOT/'backups/ms2109-maskrom.bin'
    rom = rompath.read_bytes()
    eeprom = (ROOT/'backups/ms2109-original.bin').read_bytes()
    for data, expected in ((rom,ROM_SHA),(eeprom,EEPROM_SHA)):
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Input identity differs from reviewed reference')
    size = validate(eeprom)
    checks=[]
    for name,addr,signature in SIGNATURES:
        expected=bytes.fromhex(signature)
        actual=rom[addr:addr+len(expected)]
        if actual!=expected: raise ValueError(f'{name} at {addr:04X}: {actual.hex()}')
        checks.append(dict(name=name,address=hx(addr),bytes=actual.hex()))
    code=eeprom[48:48+size]
    if code[16:31]!=bytes.fromhex('90de05ebf0a3eaf0a3e9f012634522'):
        raise ValueError('Factory CC10 helper changed')
    # Never scan the saved C000-CBFF RAM contents as ROM instructions.
    regions=[('ROM',0,rom[:0xc000]),('factory overlay',0xcc00,code)]
    refs=[]; transfers=[]; stages=[]
    for space,base,data in regions:
        for i in range(len(data)-2):
            op=data[i]; dest=int.from_bytes(data[i+1:i+3],'big')
            if op==0x90:
                refs.append(dict(space=space,site=hx(base+i),target=hx(dest),
                                 pattern='MOV DPTR,#imm16 candidate'))
            if op in (0x02,0x12) and 0xc000<=dest<0xe000:
                transfers.append(dict(space=space,site=hx(base+i),target=hx(dest),
                                      pattern='LCALL' if op==0x12 else 'LJMP'))
            if i+5<=len(data) and op==0x7f and data[i+2:i+5] in (b'\x12\x6e\xf8',b'\x02\x6e\xf8'):
                stages.append(dict(space=space,site=hx(base+i),stage=data[i+1],bytes=data[i:i+5].hex()))
    out.mkdir(parents=True,exist_ok=True)
    evidence=dict(schema_version=1,scope='offline saved artifacts; no live device state',
      inputs={'CODE_dump':{'sha256':ROM_SHA,'size':len(rom),'immutable_scan_end_exclusive':'0xC000'},
              'original_EEPROM':{'sha256':EEPROM_SHA,'size':len(eeprom),'code_length':size,
                                 'hook_flags':eeprom[4], 'checksums_valid':True}},
      rom_default_edid=decode_rom_edid(rom),
      reviewed_signatures=checks,
      candidate_warning='Raw byte matches can occur in operands or data. Not reachability, complete xrefs, register semantics, or safe-write guidance.',
      dptr_candidates=refs,overlay_transfer_candidates=transfers,stage_candidates=stages)
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    lines=['# MS2109 candidate address index','','Generated by `tools/build_programmer_reference.py`.',
      '',evidence['candidate_warning'],'','## Immediate DPTR candidates','',
      '| Target | Candidate sites (space: address) |','|---|---|']
    for dest in sorted({x['target'] for x in refs}):
        sites=', '.join(f"{x['space']}: {x['site']}" for x in refs if x['target']==dest)
        lines.append(f'| {dest} | {sites} |')
    lines+=['','## Overlay call/jump candidates','','| Source | Site | Instruction | Target |','|---|---|---|---|']
    lines += [f"| {x['space']} | {x['site']} | {x['pattern']} | {x['target']} |" for x in transfers]
    lines+=['','## Immediate normal-hook command candidates','','Stage zero uses CLR A / MOV R7,A and is verified separately. Computed commands are not enumerated.','','| Source | Site | R7 |','|---|---|---|']
    lines += [f"| {x['space']} | {x['site']} | 0x{x['stage']:02X} |" for x in stages]
    (out/'candidate-index.md').write_text('\n'.join(lines)+'\n')
    if disassemble:
        cmd='; '.join(f's {addr}; pd {count}' for addr,count in EXCERPTS)
        result=subprocess.run(['r2','-q','-a','8051','-b','8','-e','scr.color=0','-e','asm.comments=false','-c',cmd,str(rompath)],capture_output=True,text=True,check=True)
        (out/'rom-excerpts.txt').write_text(result.stdout)
    print(json.dumps({'signatures_passed':len(checks),'dptr_candidates':len(refs),
      'overlay_transfer_candidates':len(transfers),'stage_candidates':len(stages),'output':str(out)},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'artifacts/programmer-reference')
    p.add_argument('--disassemble',action='store_true',help='also emit targeted radare2 excerpts')
    args=p.parse_args()
    build(args.output,args.disassemble)
