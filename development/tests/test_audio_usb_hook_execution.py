"""Instruction-level checks for the emitted CC10 hook paths.

This intentionally models only the instructions used by the candidate and
stubs the ROM dispatcher/video callback. It does not model MS2109 peripherals.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import test_audio_usb_hook_trace as hook


class MCS51Subset:
    def __init__(self):
        patch, *_ = hook.build_patch()
        self.code = bytearray(65536)
        self.code[hook.CODE_BASE:hook.CODE_BASE + len(patch)] = patch
        self.code[0xCC10:0xCC13] = bytes.fromhex("02 d4 00")
        self.code[0xCC20:0xCC23] = bytes.fromhex("02 d4 b0")
        self.code[0x4000:0x4003] = bytes.fromhex("12 47 8f")
        self.code[0x478F:0x4792] = bytes.fromhex("12 cc 10")
        self.code[0x2000:0x2003] = bytes.fromhex("02 cc 10")
        self.code[0x2AD0:0x2AD3] = bytes.fromhex("05 20 22")  # INC 20; RET
        self.code[0x6345] = 0x22  # Stub the relocated callback's ROM service.
        self.code[0x4792:0x4794] = bytes.fromhex("80 03")
        self.code[0x4797:0x4799] = bytes.fromhex("c2 13")
        self.code[0x4799] = 0x22
        self.code[0xCC25] = 0x22
        self.code[0xCC2D] = 0x22
        self.iram = bytearray(256)
        self.sfr = {0x81: 0x30, 0x82: 0, 0x83: 0, 0xD0: 0,
                    0xE0: 0, 0xF0: 0}
        self.xdata = bytearray(65536)
        self.pc = 0x4000

    def direct(self, address):
        return self.iram[address] if address < 0x80 else self.sfr.get(address, 0)

    def write_direct(self, address, value):
        value &= 0xFF
        if address < 0x80:
            self.iram[address] = value
        else:
            self.sfr[address] = value

    def register(self, index):
        bank = (self.direct(0xD0) >> 3) & 3
        return self.iram[bank * 8 + index]

    def write_register(self, index, value):
        bank = (self.direct(0xD0) >> 3) & 3
        self.iram[bank * 8 + index] = value & 0xFF

    def fetch(self):
        value = self.code[self.pc]
        self.pc = (self.pc + 1) & 0xFFFF
        return value

    def push(self, value):
        sp = (self.direct(0x81) + 1) & 0xFF
        self.write_direct(0x81, sp)
        self.iram[sp] = value & 0xFF

    def pop(self):
        sp = self.direct(0x81)
        value = self.iram[sp]
        self.write_direct(0x81, sp - 1)
        return value

    def call(self, target):
        self.push(self.pc & 0xFF)  # 8051 stores the return low byte first.
        self.push(self.pc >> 8)
        self.pc = target

    def return_from_call(self):
        self.pc = (self.pop() << 8) | self.pop()

    def bit(self, address):
        direct = ((address & 0xF8) if address >= 0x80 else (0x20 + address // 8))
        return (self.direct(direct) >> (address & 7)) & 1

    def step(self):
        op = self.fetch()
        acc = self.sfr[0xE0]
        if op == 0x00:  # NOP
            return
        if op == 0x02:  # LJMP
            self.pc = (self.fetch() << 8) | self.fetch()
        elif op == 0x12:  # LCALL
            self.call((self.fetch() << 8) | self.fetch())
        elif op == 0x22:  # RET
            self.return_from_call()
        elif op == 0x80:  # SJMP
            rel = self.fetch()
            self.pc = (self.pc + (rel if rel < 0x80 else rel - 0x100)) & 0xFFFF
        elif op == 0x90:  # MOV DPTR,#data16
            self.sfr[0x83] = self.fetch()
            self.sfr[0x82] = self.fetch()
        elif op == 0xA3:  # INC DPTR
            dptr = ((self.sfr[0x83] << 8) | self.sfr[0x82]) + 1
            self.sfr[0x83], self.sfr[0x82] = (dptr >> 8) & 0xFF, dptr & 0xFF
        elif op == 0x04:  # INC A
            self.sfr[0xE0] = (acc + 1) & 0xFF
        elif op == 0x05:  # INC direct
            address = self.fetch()
            self.write_direct(address, self.direct(address) + 1)
        elif 0x08 <= op <= 0x0F:  # INC Rn
            index = op - 0x08
            self.write_register(index, self.register(index) + 1)
        elif op == 0x14:  # DEC A
            self.sfr[0xE0] = (acc - 1) & 0xFF
        elif op == 0x18:  # DEC R0
            self.write_register(0, self.register(0) - 1)
        elif op == 0x24:  # ADD A,#immediate
            self.sfr[0xE0] = (acc + self.fetch()) & 0xFF
        elif op == 0x30:  # JNB bit,relative
            bit, rel = self.fetch(), self.fetch()
            if not self.bit(bit):
                self.pc = (self.pc + (rel if rel < 0x80 else rel - 0x100)) & 0xFFFF
        elif op in (0x60, 0x70):  # JZ / JNZ
            rel = self.fetch()
            take = (self.sfr[0xE0] == 0) if op == 0x60 else (self.sfr[0xE0] != 0)
            if take:
                self.pc = (self.pc + (rel if rel < 0x80 else rel - 0x100)) & 0xFFFF
        elif op == 0x74:  # MOV A,#immediate
            self.sfr[0xE0] = self.fetch()
        elif op == 0x75:  # MOV direct,#immediate
            address, value = self.fetch(), self.fetch()
            self.write_direct(address, value)
        elif op == 0xA8:  # MOV R0,direct
            self.write_register(0, self.direct(self.fetch()))
        elif op == 0xB4:  # CJNE A,#immediate,relative
            immediate, rel = self.fetch(), self.fetch()
            if acc != immediate:
                self.pc = (self.pc + (rel if rel < 0x80 else rel - 0x100)) & 0xFFFF
        elif op == 0xC0:  # PUSH direct
            self.push(self.direct(self.fetch()))
        elif op == 0xC2:  # CLR bit
            bit = self.fetch()
            address = bit // 8
            self.write_direct(address, self.direct(address) & ~(1 << (bit % 8)))
        elif op == 0xD0:  # POP direct
            self.write_direct(self.fetch(), self.pop())
        elif op == 0xE0:  # MOVX A,@DPTR
            dptr = (self.sfr[0x83] << 8) | self.sfr[0x82]
            self.sfr[0xE0] = self.xdata[dptr]
        elif op == 0xE4:  # CLR A
            self.sfr[0xE0] = 0
        elif op == 0xE5:  # MOV A,direct
            self.sfr[0xE0] = self.direct(self.fetch())
        elif op == 0xE6:  # MOV A,@R0
            self.sfr[0xE0] = self.iram[self.register(0)]
        elif op == 0xE7:  # MOV A,@R1
            self.sfr[0xE0] = self.iram[self.register(1)]
        elif 0xE8 <= op <= 0xEF:  # MOV A,Rn
            self.sfr[0xE0] = self.register(op - 0xE8)
        elif op == 0xF0:  # MOVX @DPTR,A
            dptr = (self.sfr[0x83] << 8) | self.sfr[0x82]
            self.xdata[dptr] = self.sfr[0xE0]
        elif op == 0xF5:  # MOV direct,A
            self.write_direct(self.fetch(), self.sfr[0xE0])
        elif 0xF8 <= op <= 0xFF:  # MOV Rn,A
            self.write_register(op - 0xF8, self.sfr[0xE0])
        else:
            raise AssertionError(f"unsupported opcode 0x{op:02x} at 0x{self.pc - 1:04x}")

    def run_to_outer_return(self):
        for _ in range(200):
            if self.pc == 0x4003:
                return
            self.step()
        self.fail(f"did not return to caller; PC=0x{self.pc:04x}, SP=0x{self.direct(0x81):02x}")

    def fail(self, message):
        raise AssertionError(message)


class AudioUsbHookTraceTests(unittest.TestCase):
    def test_set_interface_helper_returns_before_dispatch_restore(self):
        cpu = MCS51Subset()
        cpu.iram[0x0B:0x13] = bytes((0x01, 0x0B, 0, 1, 0, 3, 0, 0))

        cpu.run_to_outer_return()

        self.assertEqual(cpu.xdata[0xDE30], 1)
        self.assertEqual(cpu.xdata[0xDE40], 0x11)
        self.assertEqual(cpu.xdata[0xDE31:0xDE33], bytes((1, 0)))
        self.assertEqual(cpu.iram[0x20], 1)  # Stock dispatcher was called once.
        self.assertEqual(cpu.direct(0x81), 0x30)  # All calls balanced the stack.

    def test_nonmatching_usb_request_is_dispatched_without_logging(self):
        cpu = MCS51Subset()
        cpu.iram[0x0B:0x13] = bytes((0x80, 0x0B, 0, 1, 0, 3, 0, 0))

        cpu.run_to_outer_return()

        self.assertEqual(cpu.xdata[0xDE30], 0)
        self.assertEqual(cpu.iram[0x20], 1)
        self.assertEqual(cpu.direct(0x81), 0x30)

    def test_video_tail_jump_uses_relocated_callback(self):
        cpu = MCS51Subset()
        cpu.code[0x4000:0x4003] = bytes.fromhex("12 20 00")
        cpu.iram[3:4] = b"\xA3"  # R3, R2, R1 values consumed by the callback.
        cpu.iram[2] = 0xB2
        cpu.iram[1] = 0xC1

        cpu.run_to_outer_return()

        self.assertEqual(cpu.xdata[0xDE05:0xDE08], bytes((0xA3, 0xB2, 0xC1)))
        self.assertEqual(cpu.xdata[0xDE30], 0)  # Video path did not parse USB fields.
        self.assertEqual(cpu.direct(0x81), 0x30)

    def test_irq_hook_records_first_ep2_ready_event_after_set_interface(self):
        cpu = MCS51Subset()
        cpu.code[0x4000:0x4003] = bytes.fromhex("12 cc 20")
        cpu.xdata[0xDE31] = 1  # SET_INTERFACE alt 1 has been observed.
        cpu.iram[0x20] = 0x04  # ROM's EP2-ready gate is set.
        cpu.iram[0x33] = 0x04  # Continue through the original IRQ tail.

        cpu.run_to_outer_return()

        self.assertEqual(cpu.xdata[0xDE30], 1)
        self.assertEqual(cpu.xdata[0xDE40], 0x22)
        self.assertEqual(cpu.xdata[0xDE32], 1)
        self.assertEqual(cpu.direct(0x81), 0x30)

    def test_irq_hook_records_ep2_ready_before_set_interface_once(self):
        cpu = MCS51Subset()
        cpu.code[0x4000:0x4003] = bytes.fromhex("12 cc 20")
        cpu.iram[0x20] = 0x04  # ROM's EP2-ready gate is set.

        cpu.run_to_outer_return()

        self.assertEqual(cpu.xdata[0xDE30], 1)
        self.assertEqual(cpu.xdata[0xDE40], 0x21)
        self.assertEqual(cpu.xdata[0xDE33], 1)
        self.assertEqual(cpu.direct(0x81), 0x30)


if __name__ == "__main__":
    unittest.main()
