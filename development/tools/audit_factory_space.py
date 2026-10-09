"""Offline factory-overlay size audit and behavior-preserving copy replacement.

Does not generate an EEPROM image or access a device. Reclaimed ranges still
need global reference/interrupt review before live use or overlay placement.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from sharpness_firmware import Asm, BASE
from build_patch import ORIGINAL_SHA, ROM_SHA, validate

ROOT = Path(__file__).resolve().parents[1]
COPY_START, COPY_END = 0xCF5E, 0xD03A
SWITCH_START, SWITCH_END, ROM_SWITCH = 0xD212, 0xD238, 0x0910
WRAPPERS = ((0xD2A2, 0x603C, 0xD27F), (0xD2A6, 0x5884, 0xD28A),
            (0xD2AA, 0x48E6, 0xCCC8), (0xD2AE, 0x6069, 0xCC28))


def compact_copy():
    """Same 149 descriptor writes and 171 DE08/09 counter writes as factory."""
    a = Asm(COPY_START)
    a.emit(0x7E, 0, 0x7A, 0xC0, 0x7B, 0xBF)  # row, destination base
    a.label('row')
    a.emit(0xE4)
    a.dptr(0xDE08)
    a.emit(0xF0, 0xA3, 0xF0, 0xFC)  # preserve original scratch writes; index=0
    a.emit(0x7D, 25, 0xEE, 0xC3, 0x94, 5)
    a.rel((0x40,), 'byte')
    a.emit(0x7D, 4)
    a.label('byte')
    a.dptr(0xCE52)
    a.emit(0xEC, 0x93, 0xFF)  # R7 = table[index]
    a.emit(0xEB, 0x2C, 0xF5, 0x82, 0xEA, 0x34, 0, 0xF5, 0x83,
           0xEF, 0xF0, 0x0C)  # write destination base + index
    a.dptr(0xDE09)
    a.emit(0xEC, 0xF0, 0x6D)
    a.rel((0x70,), 'byte')
    a.emit(0x0E, 0xEB, 0x24, 46, 0xFB, 0xEA, 0x34, 0, 0xFA)
    a.rel((0xBE, 11), 'row')
    # Restore the factory routine's observable bank-zero result registers.
    # Its final multiply has cleared OV; final comparisons leave carry clear.
    a.emit(0xE4, 0xFA, 0xFC, 0xFE, 0xF5, 0xF0,
           0x7B, 3, 0x7D, 4, 0x7F, 11, 0xC3, 0xC2, 0xD2, 0x22)
    return a


def load_inputs():
    original = (ROOT/'backups/ms2109-original.bin').read_bytes()
    rom = (ROOT/'backups/ms2109-maskrom.bin').read_bytes()
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA or hashlib.sha256(rom).hexdigest() != ROM_SHA:
        raise ValueError('Unreviewed inputs')
    return original, rom, original[48:48+validate(original)]


def experiment_overlay():
    """Return a same-length offline experiment; free bytes are poisoned FF."""
    original, rom, factory = load_inputs()
    if factory[SWITCH_START-BASE:SWITCH_END-BASE] != rom[ROM_SWITCH:ROM_SWITCH+38]:
        raise AssertionError('Switch helper is no longer a byte-exact ROM duplicate')
    a = compact_copy()
    if a.pc > COPY_END:
        raise AssertionError('Replacement exceeds factory copy region')
    b = bytearray(factory)
    b[COPY_START-BASE:COPY_END-BASE] = a.finish() + b'\xff'*(COPY_END-a.pc)
    b[0xD03C-BASE:0xD03E-BASE] = ROM_SWITCH.to_bytes(2, 'big')
    # The only two reviewed callers of the multiply are inside replaced code.
    b[0xD201-BASE:SWITCH_END-BASE] = b'\xff'*(SWITCH_END-0xD201)
    for wrapper, target, caller in WRAPPERS:
        if b[wrapper-BASE:wrapper-BASE+4] != bytes((0x12,target>>8,target&255,0x22)):
            raise AssertionError('ROM trampoline changed')
        if b[caller-BASE] not in (0x02,0x12) or b[caller-BASE+1:caller-BASE+3] != wrapper.to_bytes(2,'big'):
            raise AssertionError('Trampoline caller changed')
        b[caller-BASE+1:caller-BASE+3] = target.to_bytes(2,'big')
        b[wrapper-BASE:wrapper-BASE+4] = b'\xff'*4
    return bytes(b)


def audit(output):
    original, rom, factory = load_inputs()
    output.mkdir(parents=True, exist_ok=True)
    (output/'factory.overlay.bin').write_bytes(factory)
    linear = subprocess.check_output(['r2','-n','-a','8051','-b','8','-m',hex(BASE),'-q','-c',
                                      'e scr.color=0;pD 338 @ 0xcc00;pD 1122 @ 0xce52',
                                      str(output/'factory.overlay.bin')],text=True)
    (output/'factory-linear.txt').write_text(linear)
    (output/'compact-experiment.overlay.bin').write_bytes(experiment_overlay())
    a = compact_copy()
    (output/'compact-copy.bin').write_bytes(a.finish())
    # Table-aware decode: skip padding, EDID, descriptor data and inline switch.
    sections = [(0xCC00,0xCC1F),(0xCC20,0xCD52),(0xCE6B,0xD03E),(0xD05D,0xD2B4)]
    instructions = []
    for start,end in sections:
        result = subprocess.run(['r2','-n','-a','8051','-b','8','-m',hex(BASE),'-q','-c',
                                 f'pDj {end-start} @ {start}',str(output/'factory.overlay.bin')],
                                capture_output=True,text=True,check=True)
        items=json.loads(result.stdout)
        assert sum(item['size'] for item in items)==end-start
        instructions.extend(items)
    by_addr={item['addr']:item for item in instructions}
    table=factory[0xD03E-BASE:0xD05D-BASE]
    cases={table[pos+2]:int.from_bytes(table[pos:pos+2],'big') for pos in range(0,27,3)}
    default=int.from_bytes(table[-2:],'big')
    pending=[0xCC00,0xCC10,0xCC20];visited=set()
    while pending:
        site=pending.pop()
        if site in visited or not BASE<=site<BASE+len(factory):continue
        if site not in by_addr:raise AssertionError(f'Reachable data or undecoded address {site:04X}')
        visited.add(site);item=by_addr[site]
        if site==0xD03B:
            pending += [SWITCH_START,*cases.values(),default]
        elif item['type'] in ('ret','ujmp'):
            continue
        elif item['type']=='jmp':
            pending.append(item['jump'])
        else:
            pending.append(site+item['size'])
            if 'jump' in item:pending.append(item['jump'])
    refs=[{'site':hex(item['addr']),'target':hex(item['jump']),'type':item['type']}
          for item in instructions if 'jump' in item and BASE<=item['jump']<BASE+len(factory)]
    result={
        'scope':'offline factory audit; no live writes or smaller EEPROM image',
        'inputs':{'original_sha256':ORIGINAL_SHA,'rom_sha256':ROM_SHA},
        'copy':{'range':['0xcf5e','0xd039'],'old_bytes':COPY_END-COPY_START,
                'replacement_bytes':len(a.code),'reclaimed_bytes':COPY_END-a.pc,
                'operation':'Rows 0..4: 25 bytes; rows 5..10: 4 bytes; source CE52, destination C0BF + row*46',
                'expected_descriptor_writes':149,'expected_counter_writes':171},
        'rom_duplicate':{'overlay':'0xd212','rom':hex(ROM_SWITCH),'bytes':38,'exact_match':True,
                         'caller_redirect':'D03B LCALL D212 -> LCALL 0910'},
        'multiply':{'range':['0xd201','0xd211'],'bytes':17,
                    'reason':'Both reviewed callers are removed by the compact copy routine'},
        'trampolines': [{'overlay':hex(w),'rom':hex(t),'caller':hex(c),'bytes':4} for w,t,c in WRAPPERS],
        'reclaimed_by_experiment_bytes':COPY_END-a.pc+38+17+16,
        'unreachable_in_reviewed_graph':[
            {'address':hex(item['addr']),'bytes':item['bytes'],'instruction':item['disasm']}
            for item in instructions if item['addr'] not in visited],
        'dispatch_cases':{hex(key):hex(value) for key,value in cases.items()},
        'dispatch_default':hex(default),'reviewed_instruction_count':len(instructions),
        'reached_instruction_count':len(visited),'overlay_references':refs,
        'other_candidates':[
            {'range':['0xd28d','0xd298'],'bytes':12,'description':'Unreached alternate C-runtime startup'},
            {'range':['0xd2b2','0xd2b3'],'bytes':2,'description':'Unreached infinite-loop entry used only by that startup'},
            {'range':['0xcc1f','0xcc1f'],'bytes':1,'description':'Padding between returning helper and fixed IRQ entry'}],
        'limitations':[
            'Reachability uses known callback roots and decodes the one inline switch; not all computed ROM entries are proven absent',
            'The compact copy is a same-size offline overlay experiment; reclaimed holes are not yet packed into the Sharpness image',
            'Interrupt cycle counts differ; hardware timing and complete PSW behavior remain unqualified',
            'IRQ frame markers and video mode/no-signal logic are retained, not classified as removable'],
    }
    (output/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    for name,start,size,path in [('copy',a.origin,len(a.code),output/'compact-copy.bin'),
                                ('rom-switch',ROM_SWITCH,38,ROOT/'backups/ms2109-maskrom.bin')]:
        args=['r2','-n','-a','8051','-b','8','-q']
        if name=='copy':args+=['-m',hex(a.origin)]
        text=subprocess.check_output(args+['-c',f'e scr.color=0;pD {size} @ {start}',str(path)],text=True)
        (output/(name+'.txt')).write_text(text)
    print(json.dumps({key:result[key] for key in ('copy','rom_duplicate','reclaimed_by_experiment_bytes')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/sharpness-firmware/factory-space-audit')
    audit(parser.parse_args().output)
