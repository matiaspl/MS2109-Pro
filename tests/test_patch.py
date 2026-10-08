import sys
import unittest
import hashlib
import json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_patch import build, validate, COLOR_RECORDS, set_usb_names
from analyze_color_metadata import decode_configuration
from align_pcm import Aligner

ROOT=Path(__file__).resolve().parents[1]

# Execute the generated hook opcodes, so branch destinations, byte order and
# writes are validated independently of disassembly or byte-pattern assertions.
def execute(code, stage, memory=None, base=0):
    pc=0; a=0; dptr=0; writes={}; calls=[]; regs={i:0 for i in range(8)}
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
        elif op==0x12:
            target=int.from_bytes(code[pc:pc+2],'big');pc+=2
            if target==0x5038:
                source=(regs[2]<<8)|regs[1]
                count=(regs[4]<<8)|regs[5]
                dest=(regs[6]<<8)|regs[7]
                for i in range(count):
                    offset=source+i-base
                    value=code[offset] if 0 <= offset < len(code) else memory.get(source+i,0)
                    writes[dest+i]=value
                continue
            calls.append(pc);pc=target-base
        elif 0x78<=op<=0x7f:
            regs[op-0x78]=code[pc];pc+=1
        elif op==0x02:
            pc=int.from_bytes(code[pc:pc+2],'big')-base
        elif op==0x22:
            if calls:pc=calls.pop()
            else:return writes,dptr
        else: raise AssertionError(f'Unexpected opcode {op:02x}')
    raise AssertionError('Hook did not return')

class PatchTests(unittest.TestCase):
    def test_video_and_audio_header_name_records_and_checksums(self):
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        named=set_usb_names(original,'MS2109-Pro','MS2109-Pro')
        self.assertEqual(named[0x10:0x20],bytes((11,))+b'MS2109-Pro'+b'\xff'*5)
        self.assertEqual(named[0x20:0x30],bytes((11,))+b'MS2109-Pro'+b'\xff'*5)
        n=validate(named)
        self.assertEqual(named[48+n:50+n],(sum(named[2:48])&0xffff).to_bytes(2,'big'))
        self.assertEqual(named[50+n:52+n],original[50+n:52+n])
        for invalid in ('', 'é'*2, 'x'*16):
            with self.subTest(name=invalid), self.assertRaises(ValueError):
                set_usb_names(original, video_name=invalid)

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
        with self.assertRaises(ValueError):build(original,calibrated_color_v2=True)
        with self.assertRaises(ValueError):build(original,calibrated_color=True,calibrated_color_v2=True,rom=(ROOT/'backups/ms2109-maskrom.bin').read_bytes())

    def test_product_name_descriptor_startup_patch(self):
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        rom=(ROOT/'backups/ms2109-maskrom.bin').read_bytes()
        candidate,hook,addr=build(original,channel_order=True,calibrated_color=True,
                                  rom=rom,product_name='MS2109-Pro')
        self.assertEqual(validate(candidate),1993)
        self.assertEqual(len(candidate),2048)
        memory=dict(enumerate(rom))
        startup,_=execute(hook,1,memory,addr)
        self.assertNotIn(0xc636,startup)
        writes,_=execute(hook,2,memory,addr)
        expected=bytes((22,3))+ 'MS2109-Pro'.encode('utf-16le')
        self.assertEqual(bytes(writes[0xC636+i] for i in range(len(expected))),expected)
        self.assertEqual(candidate[2:4],bytes((0x07,0xc9)))
        self.assertEqual(candidate[50+validate(candidate):52+validate(candidate)],
                         (sum(candidate[48:48+validate(candidate)])&0xffff).to_bytes(2,'big'))
    def test_rom_get_def_constants_are_preserved(self):
        rom=(ROOT/'backups/ms2109-maskrom.bin').read_bytes()
        self.assertEqual(rom[0x4dea:0x4df2],bytes.fromhex('74f5f0a374ff8014'))
        self.assertEqual(rom[0x4df2:0x4df7],bytes.fromhex('7494124bb0'))
        self.assertEqual(rom[0x4df9:0x4dfe],bytes.fromhex('124bc48008'))
        self.assertEqual(rom[0x4dfe:0x4e06],bytes.fromhex('90c02074b4f0e4a3'))
        # GET_DEF remains mask-ROM owned; EEPROM candidates must not claim the
        # desired calibrated values until a response hook is proven safe.
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        candidate,_,_=build(original,channel_order=True,calibrated_color_v2=True,rom=rom)
        self.assertEqual(candidate[51:48+validate(original)],original[51:48+validate(original)])
    def test_candidate_hash_manifest_and_rollback_target(self):
        manifest=json.loads((ROOT/'artifacts/color-firmware/20261006/candidate-sha256.json').read_text())
        for name,digest in manifest['artifacts'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
        self.assertEqual(manifest['candidate_sha256'],manifest['artifacts']['artifacts/color-firmware/20261006/ms2109-calibrated-color-v2.bin'])
        self.assertIn('--image artifacts/ms2109-calibrated-stereo-channel-order.bin',manifest['rollback_if_candidate_is_later_flashed'])
    def test_calibrated_color_v2_shared_matrix_helper_and_eeprom_limit(self):
        original=(ROOT/'backups/ms2109-original.bin').read_bytes()
        rom=(ROOT/'backups/ms2109-maskrom.bin').read_bytes()
        patched,hook,addr=build(original,channel_order=True,calibrated_color_v2=True,rom=rom)
        self.assertEqual(patched,(ROOT/'artifacts/color-firmware/20261006/ms2109-calibrated-color-v2.bin').read_bytes())
        self.assertEqual(hashlib.sha256(patched).hexdigest(),'9de991c4f289c0d06b3997cf2b4775a088185871d8ac68eca6c72e90c38e8dfd')
        n=validate(patched)
        self.assertEqual(len(patched),2048)
        self.assertLessEqual(n,2048-52)
        memory=dict(enumerate(rom))
        for stage in range(256):
            writes,dptr=execute(hook,stage,memory,addr)
            self.assertEqual(dptr,0xde0b)
            if stage==1:
                self.assertEqual(writes,dict(zip(range(0xc6a0,0xc6a8),[238,255,149,0,0,0,147,0])) | dict(zip(range(0xfe90,0xfe94),[238,149,147,0])) | {0xc2a9:1,0xc440:1})
            elif stage==2:
                self.assertEqual(writes,{0xc4c5:2,0xc4c9:128,0xc4ca:187,0xc4cb:0,0xfe60:1,0xc2a9:1,0xc440:1})
            else:
                self.assertEqual(writes,{})
        # Both dispatch stages call the same helper address; the body exists once.
        calls=[int.from_bytes(hook[i+1:i+3],'big') for i,b in enumerate(hook[:-2]) if b==0x12 and hook[i+1:i+3]!=bytes.fromhex('d03a')]
        self.assertGreaterEqual(calls.count(calls[-1]),2)
        self.assertEqual(hook.count(bytes.fromhex('90c2a4')),1)
        overlay=bytearray(rom)
        for location,value in execute(hook,1,memory,addr)[0].items():
            if location<len(overlay):overlay[location]=value
        configuration=decode_configuration(overlay,0xc03a)
        self.assertEqual([f['color_matching']['matrix'] for f in configuration['formats']],[1,1])
        self.assertEqual(patched[51:48+validate(original)],original[51:48+validate(original)])
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
