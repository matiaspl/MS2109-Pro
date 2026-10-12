import unittest
from pathlib import Path
from transfer_metadata import edit_edid, transfer_value, parse_configuration, byte_diff, edid_eeprom_candidate, transfer_eeprom_candidate
from release_builder import matrix_patch, validate

ROOT=Path(__file__).resolve().parents[1]

class TransferMetadataTests(unittest.TestCase):
    def setUp(self):
        self.edid=(ROOT/'firmware/base/ms2109-maskrom.bin').read_bytes()[0x7738:0x7838]
    def test_gamma_only_changes_gamma_checksum(self):
        for gamma,value in ((2.4,140),(2.8,180)):
            out=edit_edid(self.edid,gamma=gamma)
            self.assertEqual(out[23],value)
            self.assertEqual({r['offset'] for r in byte_diff(self.edid,out)},{23,127})
            self.assertEqual(out[128:],self.edid[128:])
    def test_srgb_preserves_transport_and_timings(self):
        out=edit_edid(self.edid,srgb=True)
        self.assertEqual(out[23],120);self.assertTrue(out[24]&4)
        self.assertEqual(out[:23],self.edid[:23]);self.assertEqual(out[35:127],self.edid[35:127])
        self.assertEqual(out[128:],self.edid[128:])
        self.assertEqual(sum(out[:128])&255,0)
        decoded=[]
        for i in range(8):decoded.append((out[27+i]*4+((out[25+i//4]>>(6-2*(i%4)))&3))/1024)
        for actual,target in zip(decoded,(.64,.33,.30,.60,.15,.06,.3127,.3290)):
            self.assertLessEqual(abs(actual-target),.5/1024)
    def test_bad_edid_and_gamma_rejected(self):
        bad=bytearray(self.edid);bad[127]^=1
        with self.assertRaises(ValueError):edit_edid(bad,gamma=2.4)
        with self.assertRaises(ValueError):edit_edid(self.edid,gamma=2.405)
        with self.assertRaises(ValueError):edit_edid(self.edid,gamma=2.4,srgb=True)
    def test_uvc_values_are_not_codec_values(self):
        self.assertEqual(transfer_value('bt470m',0x100),2)
        self.assertEqual(transfer_value('bt470bg',0x100),3)
        self.assertEqual(transfer_value('srgb',0x110),7)
        with self.assertRaises(ValueError):transfer_value('srgb',0x100)
        with self.assertRaises(ValueError):transfer_value('bt709',None)
    def test_default_patch_is_unchanged(self):
        expected=bytearray()
        for addr in (0xc2a4,0xc43b):
            block=bytearray([0x90,addr>>8,addr&255]);branches=[]
            for i,v in enumerate(bytes.fromhex('06240d010104')):
                if i:block.append(0xa3)
                block.extend((0xe0,0xb4,v,0));branches.append(len(block)-1)
            block.extend((0x74,1,0xf0))
            for b in branches:block[b]=len(block)-(b+1)
            expected.extend(block)
        self.assertEqual(matrix_patch(),bytes(expected))
        self.assertGreater(len(matrix_patch('bt470m',0x100)),len(expected))
    def test_gate_patch_capacity_and_preservation(self):
        # Synthetic known callback exercises insertion without depending on a live artifact.
        edid=bytearray(self.edid);edid[162]=0x81;edid[255]=(-sum(edid[128:255]))&255
        self.assertEqual(edid[255],0xbd)
        n=1939;code=bytearray(b'\x00'*n)
        marker=bytes.fromhex('90fba27481f090fbff74bdf07d017f197ef812000e')
        code[-len(marker):]=marker
        image=bytearray(b'\xff'*2048);image[:2]=b'\xa5\x5a';image[2:4]=n.to_bytes(2,'big');image[48:48+n]=code
        image[48+n:50+n]=(sum(image[2:48])&65535).to_bytes(2,'big')
        image[50+n:52+n]=(sum(code)&65535).to_bytes(2,'big')
        for kw in ({'gamma':2.4},{'gamma':2.8},{'srgb':True}):
            out=edid_eeprom_candidate(bytes(image),bytes(edid),edit_edid(bytes(edid),**kw))
            self.assertLessEqual(validate(out),1996)
            self.assertEqual(out[4:48],image[4:48])
    def test_malformed_configuration_rejected(self):
        with self.assertRaises(ValueError):parse_configuration(b'\x09\x02\x09\x00\x00\x01\x00\x80\x00')
    def test_persistent_transfer_preserves_release_and_fits(self):
        rom=(ROOT/'firmware/base/ms2109-maskrom.bin').read_bytes()
        length=int.from_bytes(rom[0xc03c:0xc03e],'little')
        descriptor=rom[0xc03a:0xc03a+length]
        image=(ROOT/'firmware/ms2109-pro.bin').read_bytes()
        n=validate(image)
        for name,value in (('bt470m',2),('bt470bg',3)):
            out=transfer_eeprom_candidate(image,descriptor,0xc03a,name)
            new_n=validate(out)
            self.assertEqual(out[4:48],image[4:48])
            self.assertLessEqual(new_n,1996)
            allowed=set(range(2,4))|set(range(49,51))|set(range(48+0xd2a2-0xcc00,48+0xd2b2-0xcc00))|set(range(48+n,52+new_n))
            self.assertTrue(all(r['offset'] in allowed for r in byte_diff(image,out)))
            self.assertIn(bytes((0x15,0x82,0x74,value,0xf0,0x22)),out[48+n:48+new_n])

if __name__=='__main__':unittest.main()
