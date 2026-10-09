#!/usr/bin/env python3
"""Fail if local links in a built GitHub Pages site point to missing files."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import unquote

SKIP = ("http://", "https://", "mailto:", "data:", "javascript:", "#")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        for key in ("href", "src"):
            if key in values:
                self.targets.append(values[key])


def main(root: Path) -> int:
    root = root.resolve()
    broken = []
    checked = 0
    for page in root.rglob("*.html"):
        parser = Links()
        source = page.read_text(errors="replace")
        parser.feed(source)
        # The interactive address map assigns links from these local sources in JS.
        parser.targets.extend(re.findall(r"\bsource\s*:\s*['\"]([^'\"]+)['\"]", source))
        for target in parser.targets:
            if target.startswith(SKIP):
                continue
            path_part = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not path_part:
                continue
            if path_part.startswith("/"):
                candidate = root / path_part.lstrip("/")
            else:
                candidate = (page.parent / path_part).resolve()
            if candidate.is_dir():
                candidate /= "index.html"
            checked += 1
            if not candidate.is_file():
                broken.append((page.relative_to(root).as_posix(), target))
    if broken:
        for page, target in broken:
            print(f"BROKEN {page} -> {target}")
        print(f"{len(broken)} broken local links among {checked} checked")
        return 1
    print(f"Verified {checked} local HTML links across {len(list(root.rglob('*.html')))} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
