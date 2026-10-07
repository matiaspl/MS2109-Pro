"""Execute factory and compact routines independently; compare effects."""
import random
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from audit_factory_space import load_inputs, experiment_overlay, compact_copy, BASE, WRAPPERS
from mcs51_rom_harness import CPU

ORIGINAL, ROM, FACTORY = load_inputs()
EXPERIMENT = experiment_overlay()


class FactorySpaceTests(unittest.TestCase):
    def test_compact_copy_preserves_write_order_and_register_results(self):
        for seed in range(32):
            randomizer = random.Random(seed)
            a, b = CPU(ROM, FACTORY), CPU(ROM, EXPERIMENT)
            state = bytes(randomizer.randrange(256) for _ in range(0x50))
            table = bytes(randomizer.randrange(256) for _ in range(25))
            for machine in (a,b):
                machine.iram[:0x50] = state
                machine.put(0xD0, 0x80 if seed & 1 else 0)
                machine.put(0xF0, seed*7)
                machine.a = seed*3
                machine.xdata[0xCE52:0xCE6B] = table
                machine.run(0xCF5E)
            self.assertEqual(a.writes,b.writes,seed)
            self.assertEqual(len(a.writes),320)
            self.assertEqual(sum(0xC0BF<=addr<0xC2A0 for addr,_ in b.writes),149)
            self.assertEqual(a.iram[:0x50],b.iram[:0x50])
            for reg in (0x81,0x82,0x83,0xE0,0xF0):
                self.assertEqual(a.direct(reg),b.direct(reg),(seed,reg))
            self.assertEqual(a.direct(0xD0) & 0x84,b.direct(0xD0) & 0x84)
            self.assertFalse(any(0xD201<=pc<0xD238 for pc in b.visits))

    def test_switch_rom_replacement_all_256_commands(self):
        entries={0:0xD05D,1:0xD082,2:0xD0A8,10:0xD0DB,11:0xD082,
                 12:0xD0C8,14:0xD0D8,15:0xD0E2,20:0xD0F5}
        for command in range(256):
            outcomes=[]
            for overlay in (FACTORY,EXPERIMENT):
                c=CPU(ROM,overlay);c.setreg(7,command)
                seen=[]
                def reached(machine):
                    seen.append((machine.pc,machine.a,machine.dptr,
                                 [machine.reg(r) for r in range(8)],machine.direct(0x81)))
                    machine.ret()
                for target in set(entries.values())|{0xD0FD}:c.traps[target]=reached
                c.run(0xD03A)
                self.assertEqual(c.direct(0x81),0x50)
                self.assertEqual(len(seen),1)
                self.assertEqual(seen[0][0],entries.get(command,0xD0FD))
                outcomes.append(seen)
            self.assertEqual(*outcomes)

    def test_multiply_instruction_flags_for_factory_baseline(self):
        for left,right in ((0,255),(1,255),(2,128),(255,255),(10,46)):
            c=CPU(ROM,b'\xa4\x22');c.a=left;c.put(0xF0,right);c.carry=1
            c.run(BASE)
            self.assertEqual(c.a | c.direct(0xF0)<<8,left*right)
            self.assertEqual(c.carry,0)
            self.assertEqual(c.bit(0xD2),int(left*right>255))

    def test_direct_rom_calls_match_all_four_trampolines(self):
        for wrapper, target, _ in WRAPPERS:
            for seed in range(8):
                pair = [CPU(ROM, FACTORY), CPU(ROM, EXPERIMENT)]
                for c, entry in zip(pair, (wrapper, target)):
                    for r in range(8): c.setreg(r,(seed*31+r)&255)
                    c.a=seed*17
                    c.put(0xF0,seed*13)
                    c.put(0xD0,0x80 if seed & 1 else 0)
                    c.run(entry)
                a,b=pair
                self.assertEqual(a.writes,b.writes,(wrapper,seed))
                for reg in (*range(8),0x81,0x82,0x83,0xD0,0xE0,0xF0):
                    self.assertEqual(a.direct(reg),b.direct(reg),(wrapper,seed,reg))
                # Complete peripheral SFR trace except the intentionally shallower stack.
                self.assertEqual([(reg,value) for reg,value in a.sfr_writes if reg!=0x81],
                                 [(reg,value) for reg,value in b.sfr_writes if reg!=0x81])

    def test_only_reviewed_factory_regions_change(self):
        allowed=set(range(0xCF5E-BASE,0xD03A-BASE)) | {0xD03C-BASE,0xD03D-BASE} \
                | set(range(0xD201-BASE,0xD238-BASE))
        for wrapper, _, caller in WRAPPERS:
            allowed |= set(range(wrapper-BASE, wrapper-BASE+4)) | {caller-BASE+1,caller-BASE+2}
        changed={index for index,(a,b) in enumerate(zip(FACTORY,EXPERIMENT)) if a!=b}
        self.assertFalse(changed-allowed)
        self.assertEqual(len(compact_copy().code),78)
        self.assertEqual(len(FACTORY),len(EXPERIMENT))


if __name__=='__main__':unittest.main()
