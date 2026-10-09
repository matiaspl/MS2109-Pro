#!/usr/bin/env python3
"""Prepare an image-free Jekyll source tree from the experiments archive."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil

MEDIA = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".heic", ".dng", ".raw", ".cr2", ".nef", ".arw", ".mov", ".mp4",
    ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".mpeg", ".mpg", ".yuy2",
    ".yuvs", ".bgra", ".2vuy", ".rgba", ".ycbcr",
}

# These upstream source files are not in the repository. Point the old table
# entries to the in-repository Markdown reports that contain the relevant audit.
MISSING_SOURCE_LINKS = {
    "../upstream/macrosilicon_firmware/ms2109/rom/boot_annotated.md":
        "ms2109-reference/memory-and-boot.md",
    "../upstream/macrosilicon_firmware/ms2109/eeprom/hw_defs.h":
        "ms2109-reference/registers.md",
    "../upstream/macrosilicon_firmware/ms2109/eeprom/crt0_ms2109.asm":
        "ms2109-reference/memory-and-boot.md",
    "../upstream/ms2109_stereo_patch/MS2109_stereo_fix.cpp":
        "2026-10-07_ms2109-control-repair-report.md",
    "../upstream/ms-tools/mshal/hal_patch_gpio.go":
        "ms2109-reference/registers.md",
}

MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(<?([^)>\s]+)>?(?:\s+[^)]*)?\)")
MD_LINK = re.compile(r"(?<!!)\]\(<?([^)>\s]+\.md(?:#[^)>\s]*)?)>?\)", re.I)
HTML_ATTR = re.compile(r"(\b(?:href|src)\s*=\s*['\"])([^'\"]+)(['\"])", re.I)
JS_LOCAL_MD = re.compile(r"(['\"])([^'\"]+\.md(?:#[^'\"]*)?)\1", re.I)


def local_target(source_root: Path, parent: Path, href: str) -> Path | None:
    bare = href.split("#", 1)[0].split("?", 1)[0]
    if not bare or "://" in bare or bare.startswith(("mailto:", "data:", "javascript:", "#", "/")):
        return None
    return (parent / bare).resolve()


def html_extension(source_root: Path, parent: Path, href: str) -> str:
    if not href.lower().endswith(".md"):
        return href
    target = local_target(source_root, parent, href)
    if target is None or not target.is_file():
        return href
    return href[:-3] + ".html"


def prepare(source: Path, output: Path) -> int:
    source = source.resolve()
    output = output.resolve()
    if output == source or source in output.parents:
        raise ValueError("Output must be outside the source directory")
    if output.exists():
        shutil.rmtree(output)
    excluded_dirs = {"__pycache__", ".git"}
    copied = 0
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        if any(part in excluded_dirs for part in rel.parts):
            continue
        if rel.parts[:2] == ("artifacts", "ms2109-repair-local-only"):
            continue
        if "compiled-tools" in rel.parts:
            continue
        if path.is_dir():
            continue
        if path.suffix.lower() in MEDIA:
            continue
        dest = output / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1

    for path in output.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".md"}:
            continue
        rel = path.relative_to(output)
        text = path.read_text(errors="replace")
        if path.suffix.lower() == ".md":
            # Omit image embeds from the Pages copy while leaving source media local.
            text = MD_IMAGE.sub(lambda m: f"[{m.group(1)} — image kept locally]", text)
            def replace_md_link(match: re.Match[str]) -> str:
                target = match.group(1)
                updated = html_extension(source, path.parent, target)
                return "](" + updated + ")"
            text = MD_LINK.sub(replace_md_link, text)
        else:
            for old, new in MISSING_SOURCE_LINKS.items():
                text = text.replace(old, new)
            def replace_attr(match: re.Match[str]) -> str:
                href = html_extension(source, path.parent, match.group(2))
                return match.group(1) + href + match.group(3)
            text = HTML_ATTR.sub(replace_attr, text)
            def replace_js(match: re.Match[str]) -> str:
                href = html_extension(source, path.parent, match.group(2))
                return match.group(1) + href + match.group(1)
            text = JS_LOCAL_MD.sub(replace_js, text)
        path.write_text(text)
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="experiments source directory")
    parser.add_argument("destination", type=Path, help="temporary Jekyll source directory")
    args = parser.parse_args()
    count = prepare(args.source, args.destination)
    print(f"Prepared {count} files in {args.destination}")


if __name__ == "__main__":
    main()
