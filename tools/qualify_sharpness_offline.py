"""Export a reproducible offline qualification bundle; never access hardware."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from sharpness_firmware import assemble, BASE, restore_bytes
from build_patch import validate

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def export(directory, edid_source="custom", compact=False):
    r2 = shutil.which('r2')
    if not r2:
        raise SystemExit('radare2 is required for the independent branch/listing audit')
    original = (ROOT / 'backups/ms2109-original.bin').read_bytes()
    rom_path = ROOT / 'backups/ms2109-maskrom.bin'
    rom = rom_path.read_bytes()
    if compact:
        if edid_source != 'rom':
            raise ValueError('Compact layout requires --edid-source rom')
        from compact_sharpness import assemble_compact
        prototype = assemble_compact(original, rom)
    else:
        prototype = assemble(original, rom, edid_source=edid_source)
    directory.mkdir(parents=True, exist_ok=False)
    overlay = directory / 'offline-only.overlay.bin'
    overlay.write_bytes(prototype.overlay)
    symbols = prototype.symbols
    if compact:
        from audit_factory_space import compact_copy, WRAPPERS
        segments = [(BASE,3),(BASE+0x10,3),(0xCF5E,len(compact_copy().finish())),
                    (0xD03B,3)] + [(caller,3) for _,_,caller in WRAPPERS]
        segments += [(int(item['start'],16),item['size'])
                     for item in prototype.report['fragments'].values() if item['kind']=='code']
    else:
        segments = [(BASE, 3), (BASE+0x10, 3),
                (symbols['video'], prototype.report['edid_decoder_bytes'] or 15),
                (symbols['repair'], prototype.report['repair_bytes']),
                (symbols['common'], symbols['matrix_done']+1-symbols['common']),
                (symbols['cc10'], symbols['usb_return']+len(restore_bytes())+1-symbols['cc10']),
                (symbols['descriptor'], BASE+len(prototype.overlay)-symbols['descriptor'])]
    commands = [r2, '-n', '-a', '8051', '-b', '8', '-m', hex(BASE), '-q']
    instructions, listing = [], []
    for start, size in segments:
        result = subprocess.run(commands + ['-c', f'pDj {size} @ {start}', str(overlay)],
                                capture_output=True, text=True, check=True)
        decoded = json.loads(result.stdout)
        if sum(item['size'] for item in decoded) != size:
            raise AssertionError('Disassembly did not cover the complete code segment')
        instructions.extend(decoded)
        listing.append(f'\n; Generated code {start:04X}..{start+size-1:04X}\n')
        for item in decoded:
            names = [key for key, value in symbols.items() if value == item['addr']]
            listing.extend(name+':\n' for name in names)
            listing.append(f"{item['addr']:04X}  {item['bytes']:<16} {item['disasm']}\n")
    boundaries = {item['addr'] for item in instructions}
    rom_targets = {0x0492, 0x2AD0, 0x2B8E, 0x49C2, 0x4B10, 0x4B37,
                   0x4B69, 0x5038, 0x62CA, 0x6345}
    if compact:
        rom_targets |= {0x4B5A,0x0DC2,0x0DD9,0x0910,0x603C,0x5884,0x48E6,0x6069}
    branches = []
    for item in instructions:
        if 'jump' in item:
            target = item['jump']
            if target not in boundaries | rom_targets:
                raise AssertionError(f"Unexpected destination {item['addr']:04X}->{target:04X}")
            branches.append({'from': hex(item['addr']), 'to': hex(target),
                             'type': item['type']})
    (directory / 'decoded-hooks.txt').write_text(''.join(listing))
    (directory / 'branch-audit.json').write_text(json.dumps(branches, indent=2)+'\n')
    rom_commands = ';'.join(f'pD {size} @ {address}' for address, size in (
        (0x4780, 0x20), (0x58C8, 0x70), (0x2712, 0x55), (0x2B8E, 0x30),
        (0x49C2, 0xBA), (0x62CA, 0x55), (0x4B10, 0x70),
        (0x0C6F, 0x80), (0x0D83, 0x60), (0x5038, 0x40), (0x6345, 0x28),
        (0x0910,38)))
    result = subprocess.run([r2, '-n', '-a', '8051', '-b', '8', '-q', '-c',
                             'e scr.color=0;'+rom_commands, str(rom_path)],
                            capture_output=True, text=True, check=True)
    (directory / 'rom-contracts.txt').write_text(result.stdout)
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                            cwd=ROOT, capture_output=True, text=True)
    (directory / 'tests.txt').write_text(result.stdout+result.stderr)
    if result.returncode:
        raise SystemExit(f'Tests failed; see {directory / "tests.txt"}')
    report = prototype.report | {
        'branch_audit': {'checked_branches': len(branches), 'instruction_count': len(instructions),
                         'status': 'all generated branch/call targets are instruction boundaries or pinned ROM entries'},
        'test_command': 'python3 -m unittest discover -s tests -v',
        'test_exit_status': result.returncode,
        'r2_version': subprocess.check_output([r2, '-v'], text=True).splitlines()[0],
        'python_version': sys.version.split()[0],
        'rollback_sha256': sha((ROOT / prototype.report['rollback']).read_bytes()),
        'custom_edid_sha256': sha(original[48+0x152:48+0x252]),
        'original_checksum_validation': {'status': 'passed', 'code_bytes': validate(original)},
        'raw_overlay_sum16': hex(sum(prototype.overlay) & 65535),
        'edid_reference_audit': {
            'pinned_factory_caller': 'D118: FF:CD:52 -> CC10' if edid_source == 'custom' else 'D118: FF:77:38 -> CC10',
            'whole_saved_rom_direct_cd52_matches': rom.count(bytes.fromhex('cd52')),
            'whole_eeprom_direct_cd52_matches': original.count(bytes.fromhex('cd52')),
            'whole_eeprom_split_pointer_matches': original.count(bytes.fromhex('7acd7952')),
            'limitation': 'Literal scans and the pinned caller are not exhaustive computed-reference proof; live reuse remains gated'},
    }
    try:
        candidate = prototype.eeprom(original)
    except ValueError as error:
        report['packaging_gate'] = str(error)
        report['eeprom_image_emitted'] = False
    else:
        if not compact:
            raise AssertionError('Unexpected size change in a retained profile')
        (directory/'ms2109-sharpness-candidate.bin').write_bytes(candidate)
        report['packaging_gate'] = 'passed: exactly 2048 bytes; both checksums valid; not installed'
        report['eeprom_image_emitted'] = True
        report['candidate_sha256'] = sha(candidate)
        report['candidate_code_bytes'] = validate(candidate)
    (directory / 'qualification.json').write_text(json.dumps(report, indent=2)+'\n')
    sources = ('tools/sharpness_firmware.py', 'tools/mcs51_rom_harness.py',
               'tools/build_patch.py', 'tools/qualify_sharpness_offline.py',
               'tools/audit_sharpness_candidate_space.py', 'tests/test_sharpness_firmware.py',
               'tests/test_sharpness_rom_edid.py', 'tools/compact_sharpness.py',
               'tools/audit_factory_space.py', 'tests/test_factory_space.py',
               'tests/test_compact_sharpness.py')
    manifest = {str(path.relative_to(ROOT)): sha(path.read_bytes())
                for path in directory.iterdir() if path.is_file()}
    manifest.update({name: sha((ROOT/name).read_bytes()) for name in sources})
    (directory / 'sha256-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({'bundle': str(directory), 'code_bytes': len(prototype.overlay),
                      'deficit_bytes': report['deficit_bytes'], 'tests': 'passed',
                      'eeprom_image_emitted': report['eeprom_image_emitted']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='New output directory inside the repository')
    parser.add_argument('--edid-source', choices=('custom', 'rom'), default='custom')
    parser.add_argument('--compact',action='store_true',help='Export the compact ROM-EDID candidate')
    args = parser.parse_args()
    target = args.directory.resolve()
    target.relative_to(ROOT)
    export(target, args.edid_source, args.compact)
