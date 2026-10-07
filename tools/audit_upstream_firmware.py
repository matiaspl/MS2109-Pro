"""Assemble and size-audit the pinned public MS2109 firmware source.

This is a read-only comparison tool. It does not create an EEPROM image,
change the connected device, or claim the reconstructed overlay is qualified.
The local checkout is intentionally ignored by Git; pin its commit here so a
different upstream revision cannot silently change the audit result.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream/macrosilicon_firmware"
SOURCE = UPSTREAM / "ms2109/eeprom/crt0_ms2109.asm"
EXPECTED_COMMIT = "70434570fdcf6dcf742919826ba98fd9f8614c5d"
CODE_BASE = 0xCC00
EEPROM_SIZE = 2048
HEADER_SIZE = 0x30
CHECKSUM_SIZE = 4
RELATIVE_BRANCHES = {"sjmp", "jz", "jnz", "jc", "jnc", "jb", "jnb", "jbc", "cjne", "djnz"}


def integer_expression(source: str) -> int:
    """Evaluate only integer literals and + / - expressions from .ds."""
    tree = ast.parse(source, mode="eval")

    def visit(node: ast.AST) -> int:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            left, right = visit(node.left), visit(node.right)
            return left + right if isinstance(node.op, ast.Add) else left - right
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -visit(node.operand)
        raise ValueError(f"Unsupported assembler expression: {source}")

    return visit(tree)


def normalize_bit_operand(instruction: str) -> tuple[str, str]:
    """Convert SDAS's numeric bit addresses to radare2's byte.bit syntax."""
    parts = instruction.split(None, 1)
    opcode = parts[0]
    operands = parts[1] if len(parts) > 1 else ""
    opcode = opcode.lower()
    bit_operand = 0 if opcode in {"setb", "clr", "cpl", "jb", "jnb", "jbc"} else None
    if opcode == "mov" and operands.lower().startswith("c,"):
        bit_operand = 1
    if bit_operand is None:
        return opcode, operands

    args = operands.split(",")
    token = args[bit_operand].strip()
    if re.fullmatch(r"0x[0-9a-fA-F]{1,2}", token):
        address = int(token, 16)
        byte_address = 0x20 + address // 8 if address < 0x80 else address & 0xF8
        args[bit_operand] = f"0x{byte_address:02x}.{address % 8}"
    return opcode, ", ".join(args)


def assemble(rasm2: str, instruction: str, pc: int, labels: dict[str, int],
             all_labels: set[str], line_number: int, provisional: bool) -> bytes:
    opcode, operands = normalize_bit_operand(instruction)
    if provisional and opcode in RELATIVE_BRANCHES:
        comma = operands.rfind(",")
        operands = operands[:comma + 1] + " " + hex(pc)

    if provisional:
        operands = re.sub(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            lambda match: "0x0000" if match.group(0) in all_labels else match.group(0),
            operands,
        )
    else:
        operands = re.sub(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            lambda match: hex(CODE_BASE + labels[match.group(0)])
            if match.group(0) in labels else match.group(0),
            operands,
        )

    command = opcode + (" " + operands if operands else "")
    result = subprocess.run(
        [rasm2, "-a", "8051", "-s", hex(pc), command],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        raise ValueError(
            f"Cannot assemble source line {line_number} at {pc:04x}: {command}: "
            f"{result.stderr or result.stdout}"
        )
    return bytes.fromhex(result.stdout.strip())


def assemble_source(text: str, rasm2: str) -> tuple[bytes, dict[str, int]]:
    lines = text.splitlines()
    all_labels: set[str] = set()
    for raw in lines:
        line = raw.split(";", 1)[0].strip()
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", line)
        if match:
            all_labels.add(match.group(1))

    items: list[tuple[str, object, int]] = []
    labels: dict[str, int] = {}
    offset = 0
    for line_number, raw in enumerate(lines, start=1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if match:
            name, line = match.groups()
            if name in labels:
                raise ValueError(f"Duplicate label {name} on line {line_number}")
            labels[name] = offset
            items.append(("label", name, line_number))
            line = line.strip()
            if not line:
                continue

        if line.startswith("."):
            directive_parts = line.split(None, 1)
            directive = directive_parts[0]
            argument = directive_parts[1].strip() if len(directive_parts) > 1 else ""
            if directive in {".module", ".area"}:
                continue
            if directive == ".db":
                data = bytes(int(value.strip(), 0) for value in argument.split(","))
                items.append(("data", data, line_number))
                offset += len(data)
                continue
            if directive == ".ds":
                count = integer_expression(argument)
                if count < 0:
                    raise ValueError(f"Negative .ds size on line {line_number}")
                items.append(("fill", count, line_number))
                offset += count
                continue
            raise ValueError(f"Unsupported directive {directive} on line {line_number}")

        items.append(("instruction", line, line_number))
        offset += len(assemble(rasm2, line, CODE_BASE + offset, {}, all_labels,
                               line_number, provisional=True))

    code_size = offset
    output = bytearray()
    offset = 0
    for kind, value, line_number in items:
        if kind == "label":
            if labels[value] != offset:
                raise ValueError(f"Label layout changed at {value}")
        elif kind == "data":
            output.extend(value)
            offset += len(value)
        elif kind == "fill":
            output.extend(bytes(value))
            offset += value
        else:
            encoded = assemble(rasm2, value, CODE_BASE + offset, labels,
                               all_labels, line_number, provisional=False)
            output.extend(encoded)
            offset += len(encoded)

    if len(output) != code_size:
        raise ValueError(f"Assembler passes disagree: {len(output)} != {code_size}")
    return bytes(output), labels


def image_summary(path: Path) -> dict[str, object]:
    path = path.resolve()
    image = path.read_bytes()
    if len(image) not in (2048, 4096) or image[:2] not in (b"\xa5\x5a", b"\x96\x69"):
        raise ValueError(f"Unknown MS2109 EEPROM image: {path}")
    code_size = int.from_bytes(image[2:4], "big")
    if not HEADER_SIZE <= HEADER_SIZE + code_size + CHECKSUM_SIZE <= len(image):
        raise ValueError(f"Invalid code length in {path}")
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(image).hexdigest(),
        "code_bytes": code_size,
        "free_code_bytes": len(image) - HEADER_SIZE - code_size - CHECKSUM_SIZE,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-image", action="append", type=Path, default=[])
    args = parser.parse_args()

    args.reference_image = [
        (path if path.is_absolute() else ROOT / path).resolve()
        for path in args.reference_image
    ]

    rasm2 = shutil.which("rasm2")
    if not rasm2:
        raise SystemExit("rasm2 is required; install or select radare2 in PATH")
    commit = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != EXPECTED_COMMIT:
        raise SystemExit(f"Expected upstream {EXPECTED_COMMIT}, found {commit}")

    source = SOURCE.read_bytes()
    code, labels = assemble_source(source.decode(), rasm2)
    max_code = EEPROM_SIZE - HEADER_SIZE - CHECKSUM_SIZE
    report = {
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "upstream_commit": commit,
        "assembler": subprocess.check_output([rasm2, "-v"], text=True).splitlines()[0],
        "assembled_bytes": len(code),
        "maximum_code_bytes": max_code,
        "free_if_used_as_standalone": max_code - len(code),
        "fixed_overlay_entries": {
            name: f"0x{CODE_BASE + labels[name]:04x}"
            for name in ("_normal_hook_entry", "cmd_0c_table", "_video_config",
                         "_mul16", "_jump_table_engine", "_math_func")
        },
        "reference_images": [image_summary(path) for path in args.reference_image],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
