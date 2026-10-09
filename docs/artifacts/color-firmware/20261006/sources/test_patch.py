import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_patch import build, validate, COLOR_RECORDS
from analyze_color_metadata import decode_configuration
from align_pcm import Aligner

ROOT=Path(__file__).resolve().parents[1]

# Execute the generated hook opcodes, so branch destinations, byte order and
# writes are validated independently of disassembly or byte-pattern assertions.
def execute(code, stage, memory=None, base=0):
    pc=0; a=0; dptr=0; writes={}
    memory=memory or {}
    for _ in range(1000):
        op=code[pc]; pc+=1
        if op==0xef: a=stage
        elif op==0xb4:
            imm,rel=code[pc:pc+2]; pc+=2
            if a!=imm: pc+=rel if rel<128 else rel-256
        elif op==0x90:
            dptr=int.from_bytes(code[pc:pc+2],'big'); pc+=2
        elif op==0x74: a=code[pc]; pc+=1
        elif op==0xf0: writes[dptr]=a
        elif op==0xe0: a=writes.get(dptr,memory.get(dptr,0))
        elif op==0xa3: dptr+=1
        elif op==0x80:
            rel=code[pc];pc+=1;pc+=rel if rel<128 else rel-256
        elif op==0x02:
            pc=int.from_bytes(code[pc:pc+2],'big')-base
        elif op==0x22: return writes,dptr
        else: raise AssertionError(f'Unexpected opcode {op:02x}')
    raise AssertionError('Hook did not return')

class PatchTests(unittest.TestCase):
    def test_stage_behavior(self):
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        patched,hook,addr=build(original)
        self.assertGreater(validate(patched),validate(original))
        for stage in range(32):
            writes,dptr=execute(hook,stage)
            self.assertEqual(dptr,0xde0b)
            if stage==1:
                self.assertEqual(writes,dict(zip(range(0xc6a0,0xc6a8),[0,0,128,0,0,0,128,0])) | dict(zip(range(0xfe90,0xfe94),[0,128,128,0])))
            elif stage==2:
                self.assertEqual(writes,{0xc4c5:2,0xc4c9:128,0xc4ca:187,0xc4cb:0})
            else: self.assertEqual(writes,{})
    def test_corruption_rejected(self):
        b=bytearray((ROOT/'backups/ms2109-original.bin').read_bytes())
        b[60]^=1
        with self.assertRaises(ValueError): build(b)
    def test_channel_order_hook(self):
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        patched,hook,addr=build(original,channel_order=True)
        validate(patched)
        for stage in range(32):
            writes,dptr=execute(hook,stage)
            self.assertEqual(dptr,0xde0b)
            if stage==2:
                self.assertEqual(writes,{0xc4c5:2,0xc4c9:128,0xc4ca:187,0xc4cb:0,0xfe60:1})
            else:
                self.assertNotIn(0xfe60,writes)
    def test_calibrated_startup_and_both_descriptors(self):
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        rom=(ROOT/'backups/ms2109-maskrom.bin').read_bytes()
        patched,hook,addr=build(original,channel_order=True,calibrated_color=True,rom=rom)
        validate(patched)
        memory=dict(enumerate(rom))
        colors={0xc2a9:1,0xc440:1}
        controls=dict(zip(range(0xc6a0,0xc6a8),[238,255,149,0,0,0,147,0])) | dict(zip(range(0xfe90,0xfe94),[238,149,147,0]))
        for stage in range(256):
            writes,dptr=execute(hook,stage,memory,addr)
            self.assertEqual(dptr,0xde0b)
            if stage==1:self.assertEqual(writes,controls | colors)
            elif stage==2:self.assertEqual(writes,{0xc4c5:2,0xc4c9:128,0xc4ca:187,0xc4cb:0,0xfe60:1} | colors)
            else:self.assertEqual(writes,{})
        overlay=bytearray(rom)
        for location,value in execute(hook,1,memory,addr)[0].items():
            if location<len(overlay):overlay[location]=value
        configuration=decode_configuration(overlay,0xc03a)
        self.assertEqual([f['format'] for f in configuration['formats']],['MJPEG','YUY2'])
        for format in configuration['formats']:
            c=format['color_matching'];self.assertEqual((c['primaries'],c['transfer'],c['matrix']),(1,1,1))
        # Stock callbacks, IRQ, video tables and audio code stay byte-exact.
        n=validate(original)
        self.assertEqual(patched[51:48+n],original[51:48+n])
    def test_matrix_guards_and_repeat(self):
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        rom=(ROOT/'backups/ms2109-maskrom.bin').read_bytes()
        _,hook,addr=build(original,channel_order=True,calibrated_color=True,rom=rom)
        for record in COLOR_RECORDS:
            for byte in range(6):
                memory=dict(enumerate(rom));memory[record+byte]^=0x80
                writes,_=execute(hook,2,memory,addr)
                self.assertNotIn(record+5,writes)
        memory=dict(enumerate(rom));first,_=execute(hook,2,memory,addr)
        memory.update(first);second,_=execute(hook,2,memory,addr)
        self.assertNotIn(0xc2a9,second);self.assertNotIn(0xc440,second)
        # A full-speed template at the HS RAM base must not corrupt frame bytes.
        fs=rom[0x75cc:0x772f]
        memory={0xc03a+i:value for i,value in enumerate(fs)}
        writes,_=execute(hook,2,memory,addr)
        self.assertEqual(writes,{0xc4c5:2,0xc4c9:128,0xc4ca:187,0xc4cb:0,0xfe60:1})
    def test_calibration_requires_exact_rom(self):
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        with self.assertRaises(ValueError):build(original,calibrated_color=True)
        with self.assertRaises(ValueError):build(original,calibrated_color=True,rom=b'wrong')
    def test_legacy_image_is_reproducible(self):
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        image,_,_=build(original,channel_order=True)
        self.assertEqual(image,(ROOT/'artifacts/ms2109-neutral-stereo-channel-order.bin').read_bytes())
    def test_chunk_alignment(self):
        import struct
        correct=struct.pack('<hhhhhh',11,21,12,22,13,23)
        raw=struct.pack('<h',999)+correct
        for stride in range(1,16):
            a=Aligner(); out=b''.join(a.feed(raw[i:i+stride]) for i in range(0,len(raw),stride)); a.finish()
            self.assertEqual(out,correct)

if __name__=='__main__': unittest.main()
