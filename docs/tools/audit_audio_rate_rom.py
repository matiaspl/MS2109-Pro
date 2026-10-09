#!/usr/bin/env python3
"""Execute the saved MS2109 rate writer offline. No peripheral behavior modeled."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests'))
from test_audio_usb_hook_execution import MCS51Subset
from build_programmer_reference import ROM_SHA

class RateCPU(MCS51Subset):
    def __init__(self):
        super().__init__()
        rom = (ROOT/'backups/ms2109-maskrom.bin').read_bytes()
        if hashlib.sha256(rom).hexdigest() != ROM_SHA:
            raise ValueError('ROM identity differs')
        self.code = bytearray(65536)
        self.code[:len(rom)] = rom
        self.writes = []

    def carry(self, value):
        self.write_direct(0xD0, (self.direct(0xD0)&0x7f) | ((value&1)<<7))

    def step(self):
        op=self.code[self.pc]
        a=self.direct(0xE0)
        if op==0xf0:
            self.writes.append(((self.direct(0x83)<<8)|self.direct(0x82), a))
        if 0x78<=op<=0x7f:
            self.fetch(); self.write_register(op-0x78,self.fetch())
        elif 0xa8<=op<=0xaf:
            self.fetch(); self.write_register(op-0xa8,self.direct(self.fetch()))
        elif 0x88<=op<=0x8f:
            self.fetch(); self.write_direct(self.fetch(),self.register(op-0x88))
        elif 0x98<=op<=0x9f:
            self.fetch(); value=a-self.register(op-0x98)-(self.direct(0xd0)>>7)
            self.write_direct(0xe0,value); self.carry(value<0)
        elif op==0xc3:
            self.fetch(); self.carry(0)
        elif op==0x13:
            self.fetch(); c=self.direct(0xd0)>>7
            self.write_direct(0xe0,(a>>1)|(c<<7)); self.carry(a&1)
        elif op==0xf4:
            self.fetch(); self.write_direct(0xe0,~a)
        elif op in (0x5c,0x5d,0x4c):
            self.fetch(); r=self.register(op&7)
            self.write_direct(0xe0,a&r if op>=0x58 else a|r)
        elif op==0x42:
            self.fetch(); dest=self.fetch(); self.write_direct(dest,self.direct(dest)|a)
        elif op==0x45:
            self.fetch(); self.write_direct(0xe0,a|self.direct(self.fetch()))
        elif op==0xd8:
            self.fetch(); rel=self.fetch(); value=(self.register(0)-1)&255
            self.write_register(0,value)
            if value: self.pc=(self.pc+(rel if rel<128 else rel-256))&65535
        else:
            super().step()


def execute(input_value, output_value, initial_fe61=0, initial_f809=0):
    cpu=RateCPU()
    for i,v in enumerate(input_value.to_bytes(4,'big')): cpu.write_register(4+i,v)
    cpu.xdata[0xc56c:0xc570]=output_value.to_bytes(4,'big')
    cpu.xdata[0xfe61]=initial_fe61
    cpu.xdata[0xf809]=initial_f809
    cpu.pc=0xbfff
    cpu.call(0x3e78)
    for steps in range(5000):
        if cpu.pc==0xbfff: break
        cpu.step()
    else: raise AssertionError('Rate routine did not return')
    if cpu.direct(0x81)!=0x30: raise AssertionError('Unbalanced stack')
    peripheral=[(addr,val) for addr,val in cpu.writes if addr>=0xe000]
    return {'input':input_value,'output':output_value,'initial_fe61':initial_fe61,
      'initial_f809':initial_f809,'fe62_fe67':cpu.xdata[0xfe62:0xfe68].hex(),
      'fe61':cpu.xdata[0xfe61],'f809':cpu.xdata[0xf809],
      'c568_c56b':cpu.xdata[0xc568:0xc56c].hex(),
      'writes':[[f'{addr:04X}',f'{v:02X}'] for addr,v in peripheral],'steps':steps}

if __name__=='__main__':
    cases=[execute(x,48000,9,0x12) for x in (32000,44100,48000,88200,96000,176400,192000)]
    print(json.dumps({'rom_sha256':ROM_SHA,'scope':'actual ROM instructions; RAM/register array model, no hardware timing', 'cases':cases},indent=2))
