#!/usr/bin/env python3
"""
list-svg-sizes.py — List SVG files with their image dimensions, sorted by size or name

Usage:
    python3 tools/list-svg-sizes.py [directory] [options]

Arguments:
    directory       Root directory to search (default: current directory)

Options:
    --sort size     Sort by image dimensions (width × height) (default)
    --sort name     Sort by file name
    --sort path     Sort by full path
    --desc          Sort in descending order
    --theme THEME   Filter by theme subdirectory (e.g. Catalina-dark, Catalina-light)
    --width N       Only show files with this width
    --height N      Only show files with this height

Examples:
    python3 tools/list-svg-sizes.py
    python3 tools/list-svg-sizes.py Catalina-dark --sort name
    python3 tools/list-svg-sizes.py --sort size --desc
    python3 tools/list-svg-sizes.py --width 16
"""

import sys
import argparse
import re
from pathlib import Path
from lxml import etree


def parse_length(value: str) -> float | None:
    """Parse an SVG length value, stripping units (px, pt, etc.)."""
    if value is None:
        return None
    m = re.match(r"^\s*([\d.]+)\s*(px|pt|mm|cm|in|em|rem|%)?\s*$", value)
    if m:
        return float(m.group(1))
    return None


def get_svg_dimensions(path: Path) -> tuple[float, float] | None:
    """Return (width, height) in pixels from an SVG file, or None if unreadable."""
    try:
        parser = etree.XMLParser(recover=True, resolve_entities=False)
        tree = etree.parse(str(path), parser)
        root = tree.getroot()

        tag = root.tag
        if tag.startswith("{"):
            tag = tag.split("}")[1]
        if tag != "svg":
            return None

        w = parse_length(root.get("width"))
        h = parse_length(root.get("height"))

        if w is not None and h is not None:
            return (w, h)

        # Fall back to viewBox
        vb = root.get("viewBox")
        if vb:
            parts = re.split(r"[\s,]+", vb.strip())
            if len(parts) == 4:
                try:
                    return (float(parts[2]), float(parts[3]))
                except ValueError:
                    pass
    except Exception:
        pass
    return None


def collect_svgs(root: Path, filter_w: int | None, filter_h: int | None) -> list[dict]:
    results = []
    for path in root.rglob("*.svg"):
        if not path.is_file() or path.is_symlink():
            continue
        dims = get_svg_dimensions(path)
        if dims is None:
            w, h = None, None
        else:
            w, h = dims

        if filter_w is not None and w != filter_w:
            continue
        if filter_h is not None and h != filter_h:
            continue

        results.append({
            "path": path,
            "rel": path.relative_to(root),
            "name": path.name,
            "width": w,
            "height": h,
            "area": (w * h) if (w is not None and h is not None) else -1,
        })
    return results


def fmt_dims(w, h) -> str:
    if w is None or h is None:
        return "   ?×?"
    wx = int(w) if w == int(w) else w
    hx = int(h) if h == int(h) else h
    return f"{wx:>4}×{hx:<4}"


def main():
    parser = argparse.ArgumentParser(description="List SVG files by image dimensions.")
    parser.add_argument("directory", nargs="?", default=".", help="Root directory to search")
    parser.add_argument("--sort", choices=["size", "name", "path"], default="size",
                        help="Sort field (default: size)")
    parser.add_argument("--desc", action="store_true", help="Sort descending")
    parser.add_argument("--theme", default=None, metavar="THEME",
                        help="Filter by theme subdirectory name")
    parser.add_argument("--width", type=float, default=None, metavar="N",
                        help="Only show files with this width")
    parser.add_argument("--height", type=float, default=None, metavar="N",
                        help="Only show files with this height")
    args = parser.parse_args()

    root = Path(args.directory).resolve()
    if not root.is_dir():
        print(f"Error: '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    if args.theme:
        root = root / args.theme
        if not root.is_dir():
            print(f"Error: theme directory '{root}' not found.", file=sys.stderr)
            sys.exit(1)

    print("Scanning SVG files...", end="\r", file=sys.stderr)
    svgs = collect_svgs(root, args.width, args.height)
    sys.stderr.write("\033[2K\r")  # clear the scanning line

    if not svgs:
        print("No SVG files found.")
        return

    key_map = {
        "size": lambda e: (e["area"], str(e["rel"])),
        "name": lambda e: (e["name"], e["area"]),
        "path": lambda e: str(e["rel"]),
    }
    svgs.sort(key=key_map[args.sort], reverse=args.desc)

    max_path_len = max(len(str(e["rel"])) for e in svgs)
    col_path = min(max_path_len, 80)
    sep = "-" * (col_path + 14)

    print(f"{'DIMENSIONS':>10}  PATH")
    print(sep)

    for entry in svgs:
        dims = fmt_dims(entry["width"], entry["height"])
        print(f"{dims}  {entry['rel']}")

    print(sep)
    print(f"{len(svgs)} files")


if __name__ == "__main__":
    main()
