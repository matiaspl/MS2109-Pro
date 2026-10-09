"""Instruction harness for the pinned MS2109 control routines.

Executes ROM instructions. Only SFR AB FIFO contents and SFR 80 availability
are supplied by the test; no timing, electrical USB or interrupt model.
"""
from collections import deque


class CPU:
    def __init__(self, rom, overlay=b''):
        self.code = bytearray(65536)
        self.code[:len(rom)] = rom
        self.xdata = bytearray(65536)
        self.xdata[0xC000:len(rom)] = rom[0xC000:]
        self.xdata[0xCC00:0xCC00+len(overlay)] = overlay
        self.code[0xCC00:0xCC00+len(overlay)] = overlay
        self.iram = bytearray(256)
        self.sfr = bytearray(128)
        self.sfr[1] = 0x50
        self.pc = 0
        self.input = deque()
        self.output = bytearray()
        self.writes = []
        self.sfr_writes = []
        self.visits = set()
        self.calls = []
        self.traps = {}

    def direct(self, address):
        if address == 0xAB:
            if not self.input:
                raise AssertionError('EP0 read beyond supplied OUT payload')
            return self.input.popleft()
        return self.iram[address] if address < 128 else self.sfr[address-128]

    def put(self, address, value):
        value &= 255
        if address < 128:
            self.iram[address] = value
        else:
            self.sfr[address-128] = value
            self.sfr_writes.append((address, value))
            if address == 0xAB:
                self.output.append(value)

    @property
    def a(self): return self.direct(0xE0)
    @a.setter
    def a(self, value): self.put(0xE0, value)
    @property
    def carry(self): return self.direct(0xD0) >> 7
    @carry.setter
    def carry(self, value): self.put(0xD0, (self.direct(0xD0) & 127) | (bool(value) << 7))
    @property
    def dptr(self): return self.direct(0x82) | self.direct(0x83) << 8
    @dptr.setter
    def dptr(self, value):
        self.put(0x82, value)
        self.put(0x83, value >> 8)

    def reg(self, index):
        return self.iram[(self.direct(0xD0) & 0x18) + index]

    def setreg(self, index, value):
        self.iram[(self.direct(0xD0) & 0x18) + index] = value & 255

    def bit(self, bit):
        address = (0x20 + bit // 8) if bit < 128 else (bit & 0xF8)
        return self.direct(address) >> (bit & 7) & 1

    def setbit(self, bit, value):
        address = (0x20 + bit // 8) if bit < 128 else (bit & 0xF8)
        mask = 1 << (bit & 7)
        self.put(address, (self.direct(address) & ~mask) | (mask if value else 0))

    def fetch(self):
        value = self.read_code(self.pc)
        self.pc = (self.pc + 1) & 65535
        return value

    def read_code(self, address):
        return self.xdata[address] if 0xC000 <= address < 0xE000 else self.code[address]

    def relative(self, condition):
        offset = self.fetch()
        if condition:
            self.pc = (self.pc + (offset if offset < 128 else offset - 256)) & 65535

    def push(self, value):
        sp = (self.direct(0x81) + 1) & 255
        self.put(0x81, sp)
        self.iram[sp] = value

    def pop(self):
        sp = self.direct(0x81)
        result = self.iram[sp]
        self.put(0x81, sp - 1)
        return result

    def call(self, address):
        self.push(self.pc & 255)
        self.push(self.pc >> 8)
        self.calls.append(address)
        self.pc = address

    def ret(self):
        high = self.pop()
        self.pc = (high << 8) | self.pop()

    def write_xdata(self, address, value):
        self.xdata[address] = value & 255
        self.writes.append((address, value & 255))

    def operand(self, low):
        if low == 4: return self.fetch()
        if low == 5: return self.direct(self.fetch())
        if low in (6, 7): return self.iram[self.reg(low-6)]
        return self.reg(low-8)

    def step(self):
        self.visits.add(self.pc)
        if self.pc in self.traps:
            self.traps[self.pc](self)
            return
        at = self.pc
        op = self.fetch()
        if op == 0: return
        if op in (0x02, 0x12):
            dest = self.fetch() << 8 | self.fetch()
            if op == 0x12: self.call(dest)
            else: self.pc = dest
        elif op & 0x1F in (1, 0x11):
            low = self.fetch()
            dest = (self.pc & 0xF800) | ((op & 0xE0) << 3) | low
            if op & 0x1F == 0x11: self.call(dest)
            else: self.pc = dest
        elif op in (0x22, 0x32): self.ret()
        elif op == 0x80: self.relative(True)
        elif op in (0x40, 0x50, 0x60, 0x70):
            self.relative({0x40: self.carry, 0x50: not self.carry,
                           0x60: self.a == 0, 0x70: self.a != 0}[op])
        elif op in (0x10, 0x20, 0x30):
            bit = self.fetch()
            value = self.bit(bit)
            self.relative(not value if op == 0x30 else value)
            if op == 0x10 and value: self.setbit(bit, 0)
        elif op in (0xC2, 0xD2, 0xB2):
            bit = self.fetch()
            self.setbit(bit, not self.bit(bit) if op == 0xB2 else op == 0xD2)
        elif op in (0xC3, 0xD3, 0xB3):
            self.carry = not self.carry if op == 0xB3 else op == 0xD3
        elif op == 0xA2: self.carry = self.bit(self.fetch())
        elif op == 0x92: self.setbit(self.fetch(), self.carry)
        elif op == 0x90: self.dptr = self.fetch() << 8 | self.fetch()
        elif op == 0xA3: self.dptr = (self.dptr + 1) & 65535
        elif op == 0xE0: self.a = self.xdata[self.dptr]
        elif op == 0xF0: self.write_xdata(self.dptr, self.a)
        elif op == 0x93: self.a = self.read_code((self.dptr + self.a) & 65535)
        elif op == 0x83: self.a = self.read_code((self.pc + self.a) & 65535)
        elif op == 0x73: self.pc = (self.dptr + self.a) & 65535
        elif op == 0xE4: self.a = 0
        elif op == 0xF4: self.a = ~self.a
        elif op == 0x74: self.a = self.fetch()
        elif op == 0x75:
            dest = self.fetch()
            self.put(dest, self.fetch())
        elif op == 0x85:
            value = self.direct(self.fetch())
            self.put(self.fetch(), value)
        elif op == 0xE5: self.a = self.direct(self.fetch())
        elif op == 0xF5: self.put(self.fetch(), self.a)
        elif 0x78 <= op <= 0x7F: self.setreg(op & 7, self.fetch())
        elif 0xA8 <= op <= 0xAF: self.setreg(op & 7, self.direct(self.fetch()))
        elif 0x88 <= op <= 0x8F: self.put(self.fetch(), self.reg(op & 7))
        elif 0xE8 <= op <= 0xEF: self.a = self.reg(op & 7)
        elif 0xF8 <= op <= 0xFF: self.setreg(op & 7, self.a)
        elif op in (0xE6, 0xE7): self.a = self.iram[self.reg(op & 1)]
        elif op in (0xF6, 0xF7): self.iram[self.reg(op & 1)] = self.a
        elif op in (0x76, 0x77): self.iram[self.reg(op & 1)] = self.fetch()
        elif op in (0xC0, 0xD0):
            dest = self.fetch()
            if op == 0xC0: self.push(self.direct(dest))
            else: self.put(dest, self.pop())
        elif op == 0x04: self.a += 1
        elif op == 0x14: self.a -= 1
        elif op in (0x05, 0x15):
            dest = self.fetch()
            self.put(dest, self.direct(dest) + (1 if op == 5 else -1))
        elif 0x08 <= op <= 0x0F: self.setreg(op & 7, self.reg(op & 7) + 1)
        elif 0x18 <= op <= 0x1F: self.setreg(op & 7, self.reg(op & 7) - 1)
        elif 0x24 <= op <= 0x2F or 0x34 <= op <= 0x3F or 0x94 <= op <= 0x9F:
            value = self.operand(op & 15)
            old = self.a
            if op < 0x30: result = old + value
            elif op < 0x40: result = old + value + self.carry
            else: result = old - value - self.carry
            self.carry = result < 0 or result > 255
            self.a = result
        elif 0x44 <= op <= 0x4F or 0x54 <= op <= 0x5F or 0x64 <= op <= 0x6F:
            value = self.operand(op & 15)
            self.a = (self.a | value) if op < 0x50 else ((self.a & value) if op < 0x60 else self.a ^ value)
        elif op in (0x42, 0x52, 0x62, 0x43, 0x53, 0x63):
            dest = self.fetch()
            value = self.fetch() if op & 1 else self.a
            old = self.direct(dest)
            self.put(dest, old | value if op < 0x50 else (old & value if op < 0x60 else old ^ value))
        elif op == 0xB4 or op == 0xB5 or 0xB8 <= op <= 0xBF:
            if op in (0xB4, 0xB5):
                left = self.a
                right = self.fetch() if op == 0xB4 else self.direct(self.fetch())
            else:
                left, right = self.reg(op & 7), self.fetch()
            self.carry = left < right
            self.relative(left != right)
        elif op == 0xD5 or 0xD8 <= op <= 0xDF:
            if op == 0xD5:
                dest = self.fetch()
                value = (self.direct(dest) - 1) & 255
                self.put(dest, value)
            else:
                value = (self.reg(op & 7) - 1) & 255
                self.setreg(op & 7, value)
            self.relative(value != 0)
        elif op in (0x03, 0x13, 0x23, 0x33):
            old, carry = self.a, self.carry
            if op == 3: self.a = old >> 1 | (old & 1) << 7
            elif op == 0x23: self.a = old << 1 | old >> 7
            elif op == 0x13: self.a = old >> 1 | carry << 7; self.carry = old & 1
            else: self.a = old << 1 | carry; self.carry = old >> 7
        elif 0xC8 <= op <= 0xCF:
            value = self.reg(op & 7)
            self.setreg(op & 7, self.a)
            self.a = value
        elif op == 0xA4:
            product = self.a * self.direct(0xF0)
            self.a = product & 255
            self.put(0xF0, product >> 8)
            self.carry = 0
            self.setbit(0xD2, product > 255)  # MUL defines OV; AC is undefined.
        elif op == 0xC5:
            dest = self.fetch()
            value = self.direct(dest)
            self.put(dest, self.a)
            self.a = value
        else:
            raise AssertionError(f'unsupported opcode {op:02x} at {at:04x}')

    def run(self, entry, return_to=0xBFFE, limit=200000):
        self.pc = return_to
        self.call(entry)
        for _ in range(limit):
            if self.pc == return_to: return
            self.step()
        raise AssertionError(f'CPU did not return; PC={self.pc:04x}')
