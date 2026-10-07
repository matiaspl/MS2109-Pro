"""Execute compact linked code against the same ROM acceptance contracts."""
import unittest
from unittest.mock import patch
from tests import test_sharpness_firmware as firmware
from tests import test_factory_space as factory
from compact_sharpness import assemble_compact, POOLS, LinkAsm, link
from audit_factory_space import WRAPPERS
from build_patch import build, validate

VARIANT = assemble_compact(firmware.ORIGINAL, firmware.ROM)


class CompactSharpnessTests(firmware.SharpnessFirmwareTests):
    def setUp(self):
        replacement = patch.object(firmware, 'PROTOTYPE', VARIANT)
        replacement.start()
        self.addCleanup(replacement.stop)

    def allowed_factory_changes(self):
        allowed = super().allowed_factory_changes()
        for start, end in ((0xCC13,0xCC20),(0xCF5E,0xD03A),
                           (0xD201,0xD238),(0xD2A2,0xD2B2)):
            allowed.update(range(start-0xCC00,end-0xCC00))
        allowed.update((0xD03C-0xCC00,0xD03D-0xCC00))
        for _, _, caller in WRAPPERS:
            allowed.update((caller+1-0xCC00,caller+2-0xCC00))
        return allowed

    def test_oversize_profile_never_emits_eeprom(self):
        # This subclass now fits; the other profiles retain their refusal tests.
        image, overlay, entry = build(firmware.ORIGINAL, rom=firmware.ROM,
            sharpness_profile=True, sharpness_edid='rom', compact_sharpness=True)
        self.assertEqual(image, VARIANT.eeprom(firmware.ORIGINAL))
        self.assertEqual(len(image),2048)
        self.assertEqual(validate(image),len(VARIANT.overlay))
        self.assertLessEqual(validate(image),1996)
        self.assertEqual(image[4],7)
        self.assertEqual((overlay,entry),(VARIANT.overlay,0xCC00))
        self.assertEqual(image[52+len(overlay):],b'\xff'*(1996-len(overlay)))

    def test_allocations_and_retained_startup(self):
        ranges=[]
        for item in VARIANT.report['fragments'].values():
            start=int(item['start'],16); end=start+item['size']
            self.assertTrue(any(base<=start and end<=base+capacity
                for base,capacity in POOLS if capacity is not None) or
                POOLS[-1][0]<=start<end<=0xD3CC)
            self.assertTrue(all(end<=a or start>=b for a,b in ranges))
            ranges.append((start,end))
        for start,end in ((0xD28D,0xD299),(0xD2B2,0xD2B4),(0xCE52,0xCE6B)):
            self.assertEqual(VARIANT.overlay[start-0xCC00:end-0xCC00],
                             firmware.ORIGINAL[48+start-0xCC00:48+end-0xCC00])

    def test_factory_copy_in_final_packed_overlay(self):
        with patch.object(factory,'EXPERIMENT',VARIANT.overlay):
            factory.FactorySpaceTests().test_compact_copy_preserves_write_order_and_register_results()

    def test_factory_switch_in_final_packed_overlay(self):
        with patch.object(factory,'EXPERIMENT',VARIANT.overlay):
            factory.FactorySpaceTests().test_switch_rom_replacement_all_256_commands()

    def test_uncompacted_rom_profile_remains_reproducible(self):
        previous=firmware.assemble(firmware.ORIGINAL,firmware.ROM,edid_source='rom')
        self.assertEqual(previous.report['overlay_sha256'],
                         'dbaeef003752048f70877afd397ca2c3e750d26ec7855107832746e72d98012c')


class LinkerTests(unittest.TestCase):
    def test_page_calls_and_jumps_at_page_boundary(self):
        # The page is taken from PC after the two-byte instruction, not its start.
        for origin in (0xCFFE,0xD000):
            for target in (0xC800,0xD100,0xD7FF,0xD800):
                for operation in ('call','jump'):
                    a=LinkAsm();a.label('start');getattr(a,operation)(target)
                    with patch('compact_sharpness.POOLS',((origin,None),)):
                        result=link({'start':a.nodes},[['start']])
                    code=result[2]['start']
                    same_page=((origin+2)&0xF800)==(target&0xF800)
                    self.assertEqual(len(code),2 if same_page else 3)
                    c=firmware.CPU(firmware.ROM,b'\xff'*0x1000)
                    c.xdata[origin:origin+len(code)]=code
                    c.pc=origin;c.step()
                    self.assertEqual(c.pc,target)
                    if operation=='call':
                        c.ret();self.assertEqual(c.pc,origin+len(code))


if __name__=='__main__':unittest.main()
