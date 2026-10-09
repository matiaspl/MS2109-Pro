"""Trace the known EEPROM entry roots against the pinned ROM and overlay.

This is a bounded emulator check. The CPU model has no interrupt scheduler or
hardware timing model; unknown/unmapped code addresses stop the trace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from audit_factory_space import BASE, ORIGINAL_SHA, ROM_SHA, load_inputs
from mcs51_rom_harness import CPU

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'artifacts/sharpness-firmware/factory-space-audit/startup-root-traces.json'
CANDIDATE_RANGES = ((0xD28D, 0xD299), (0xD2B2, 0xD2B4))
ENTRY_ROOTS = (0xCC00, 0xCC10, 0xCC20)


class TraceCPU(CPU):
    def __init__(self, rom: bytes, overlay: bytes):
        super().__init__(rom, overlay)
        self.executed_instructions = 0
        self.computed_jumps: list[dict[str, str]] = []
        self.rom_end = len(rom)
        self.overlay_end = BASE + len(overlay)

    def step(self):
        if not (0 <= self.pc < self.rom_end or BASE <= self.pc < self.overlay_end):
            raise RuntimeError(f'unmapped code PC {self.pc:04X}')
        at = self.pc
        opcode = self.read_code(at)
        dptr, accumulator = self.dptr, self.a
        self.executed_instructions += 1
        super().step()
        if opcode == 0x73:
            self.computed_jumps.append({
                'site': f'{at:04X}', 'dptr': f'{dptr:04X}',
                'a': f'{accumulator:02X}', 'target': f'{self.pc:04X}',
            })


def trace_root(rom: bytes, overlay: bytes, entry: int) -> dict:
    cpu = TraceCPU(rom, overlay)
    try:
        cpu.run(entry, limit=300_000)
        result = 'returned to harness sentinel'
    except Exception as error:  # Preserve partial coverage and the stop reason.
        result = f'{type(error).__name__}: {error}'
    candidate_visits = sorted(
        pc for pc in cpu.visits
        if any(start <= pc < end for start, end in CANDIDATE_RANGES)
    )
    return {
        'root': f'{entry:04X}', 'result': result,
        'executed_instructions': cpu.executed_instructions,
        'unique_program_counters': len(cpu.visits),
        'candidate_addresses_visited': [f'{pc:04X}' for pc in candidate_visits],
        'computed_jumps': cpu.computed_jumps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    _, rom, overlay = load_inputs()
    result = {
        'scope': 'instruction-level emulator trace from the three documented overlay roots, using default IRAM/SFR/XDATA state; no device access',
        'harness': 'tools/mcs51_rom_harness.py CPU with PC and JMP @A+DPTR tracing; stops outside saved ROM/overlay ranges',
        'inputs': {'mask_rom_sha256': ROM_SHA, 'original_eeprom_sha256': ORIGINAL_SHA},
        'traces': [trace_root(rom, overlay, entry) for entry in ENTRY_ROOTS],
        'interpretation': 'A root trace that returns without visiting a candidate only covers that modeled state. It does not prove unreachability for other register/peripheral states, interrupts, or all computed DPTR values.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
