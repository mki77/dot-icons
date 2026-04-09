#!/usr/bin/env python3
"""
cleanup-svgs.py — Validate, fix, and optimize SVG files

Usage:
  ./cleanup-svgs.py [OPTIONS] <directory|file.svg>

Options:
  --check      Validate XML only, do not modify files
  --fix-size   Remove invisible rects and fix SVG dimensions to match target
  --scale-up   Scale up undersized drawings to fill icon canvas (needs inkscape)
  --help       Show this help message

Examples:
  ./cleanup-svgs.py Catalina-light/actions/22/
  ./cleanup-svgs.py --check Catalina-dark/
  ./cleanup-svgs.py --fix-size --scale-up Catalina-dark/status/16/
  ./cleanup-svgs.py Catalina-light/apps/scalable/myapp.svg
"""

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def get_target_size(path):
    """Extract target size from the last numeric directory segment of the path."""
    m = re.findall(r'/(\d+)/', str(path))
    return int(m[-1]) if m else None


def make_bar(n, total, width=25):
    filled = int(width * n / total) if total else width
    return f"[{'#' * filled}{'-' * (width - filled)}] {n}/{total}"


def progress(n, total):
    print(f"\r  {make_bar(n, total)}", end='', flush=True)


def note(msg):
    """Print a permanent line, clearing the progress bar first."""
    print(f"\r{' ' * 72}\r  {msg}", flush=True)


def human_size(b):
    if b >= 1_048_576:
        return f"{b / 1_048_576:.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


# ── Phase 1: XML validation ───────────────────────────────────────────────────

def phase_validate(svg_files):
    print("\n=== Validating XML ===")
    total = len(svg_files)
    errors = {}

    for i, svg in enumerate(svg_files, 1):
        r = subprocess.run(["xmllint", "--noout", svg],
                           capture_output=True, text=True)
        if r.returncode != 0:
            errors[svg] = r.stderr.strip()
        if i % 25 == 0 or i == total:
            progress(i, total)
    print()

    if errors:
        print(f"ERRORS: {len(errors)} file(s) with XML errors:\n")
        for msg in errors.values():
            print(msg)
        print()
    else:
        print(f"All {total} files passed XML validation.")

    return errors


# ── Phase 2: Fix SVG dimensions ───────────────────────────────────────────────

def fix_svg(svg_file, target):
    t = str(target)
    with open(svg_file) as f:
        content = f.read()
    original = content

    # Remove invisible rects/ellipses (self-closing, single-line)
    content = re.sub(
        r'[ \t]*<(rect|ellipse)\b[^>]*\b(?:fill-)?opacity="0"[^>]*/>\s*\n?',
        '', content)

    svg_m = re.search(r'(<svg\b)([\s\S]*?)(>)', content)
    if not svg_m:
        if content != original:
            with open(svg_file, 'w') as f:
                f.write(content)
            return "cleaned"
        return None

    attrs = svg_m.group(2)
    w_m  = re.search(r'\bwidth="([^"]*)"',   attrs)
    h_m  = re.search(r'\bheight="([^"]*)"',  attrs)
    vb_m = re.search(r'\bviewBox="([^"]*)"', attrs)
    cur_w = w_m.group(1) if w_m else None
    cur_h = h_m.group(1) if h_m else None

    if cur_w == t and cur_h == t:
        if content != original:
            with open(svg_file, 'w') as f:
                f.write(content)
            return "cleaned"
        return None

    new_attrs = attrs

    # Add viewBox from original dimensions before overwriting width/height
    if not vb_m and cur_w and cur_h:
        try:
            vb_w = int(round(float(cur_w)))
            vb_h = int(round(float(cur_h)))
            new_attrs = new_attrs.replace(
                w_m.group(0), f'viewBox="0 0 {vb_w} {vb_h}" width="{t}"')
        except ValueError:
            new_attrs = new_attrs.replace(w_m.group(0), f'width="{t}"')
    elif w_m:
        new_attrs = new_attrs.replace(w_m.group(0), f'width="{t}"')

    if h_m:
        new_attrs = new_attrs.replace(h_m.group(0), f'height="{t}"')
    else:
        new_attrs += f' height="{t}"'

    if not w_m:
        new_attrs = f' width="{t}"' + new_attrs

    content = content[:svg_m.start(2)] + new_attrs + content[svg_m.end(2):]
    with open(svg_file, 'w') as f:
        f.write(content)

    old = f"{cur_w}x{cur_h}" if cur_w and cur_h else "missing"
    return f"size {old} -> {t}x{t}"


def phase_fix_size(svg_files):
    print("\n=== Fixing SVG dimensions ===")
    total = len(svg_files)
    count = errors = 0

    for i, svg in enumerate(svg_files, 1):
        target = get_target_size(svg)
        if target:
            try:
                result = fix_svg(svg, target)
                if result:
                    note(f"FIXED ({result}): {Path(svg).name}")
                    count += 1
            except Exception as e:
                note(f"ERROR ({e}): {Path(svg).name}")
                errors += 1
        progress(i, total)

    print(f"\n  Fixed {count} file(s)" + (f", {errors} error(s)" if errors else ""),
          flush=True)


# ── Phase 3: Scale up undersized drawings ────────────────────────────────────

def get_drawing_bbox(svg_file):
    try:
        r = subprocess.run(
            ['timeout', '20', 'inkscape', '--query-all', svg_file],
            capture_output=True, text=True, timeout=25)
        if r.returncode != 0 or not r.stdout.strip():
            err = (r.stderr.strip().split('\n')[0] if r.stderr.strip()
                   else f"exit {r.returncode}" if r.returncode else "no output")
            return None, err
        for line in r.stdout.splitlines():
            parts = line.strip().split(',')
            if len(parts) >= 5:
                try:
                    return tuple(float(p) for p in parts[1:5]), None
                except ValueError:
                    continue
        return None, "no bbox data in inkscape output"
    except subprocess.TimeoutExpired:
        return None, "timeout (>25s)"
    except FileNotFoundError:
        return None, "inkscape not found"
    except Exception as e:
        return None, str(e)


def do_scale(svg_file, target, bbox):
    dx, dy, dw, dh = bbox
    if max(dw, dh) >= target - 1:
        return None

    with open(svg_file) as f:
        content = f.read()

    svg_m = re.search(r'(<svg\b)([\s\S]*?)(>)', content)
    if not svg_m:
        return None

    attrs = svg_m.group(2)
    w_m  = re.search(r'\bwidth="([^"]*)"',  attrs)
    h_m  = re.search(r'\bheight="([^"]*)"', attrs)
    vb_m = re.search(r'viewBox="([^"]*)"',  attrs)

    svg_w = float(w_m.group(1)) if w_m else target
    svg_h = float(h_m.group(1)) if h_m else target

    if vb_m:
        vb_x, vb_y, vb_w, vb_h = map(float, vb_m.group(1).split())
        scale_x, scale_y = vb_w / svg_w, vb_h / svg_h
        real_x = vb_x + dx * scale_x
        real_y = vb_y + dy * scale_y
        real_w = dw * scale_x
        real_h = dh * scale_y
    else:
        real_x, real_y, real_w, real_h = dx, dy, dw, dh

    def fmt(v):
        return "0" if abs(v) < 0.001 else f"{v:.4g}"
    new_vb = f"{fmt(real_x)} {fmt(real_y)} {fmt(real_w)} {fmt(real_h)}"

    if vb_m:
        new_attrs = attrs.replace(vb_m.group(0), f'viewBox="{new_vb}"')
    else:
        new_attrs = f' viewBox="{new_vb}"' + attrs

    content = content[:svg_m.start(2)] + new_attrs + content[svg_m.end(2):]
    with open(svg_file, 'w') as f:
        f.write(content)

    return real_w, real_h


def phase_scale_up(svg_files, jobs):
    print(f"\n=== Scaling up undersized drawings (parallel: {jobs} jobs) ===")
    total = len(svg_files)
    lock = threading.Lock()
    done = scaled = errors = 0

    def _progress():
        print(f"\r  {make_bar(done, total)}", end='', flush=True)

    def process(svg):
        nonlocal done, scaled, errors
        target = get_target_size(svg)
        if not target:
            with lock:
                done += 1
                _progress()
            return

        bbox, err = get_drawing_bbox(svg)
        if err:
            with lock:
                done += 1
                errors += 1
                note(f"ERROR ({err}): {Path(svg).name}")
                _progress()
            return

        result = do_scale(svg, target, bbox)
        with lock:
            done += 1
            if result:
                scaled += 1
                dw, dh = bbox[2], bbox[3]
                note(f"SCALED ({dw:.1f}x{dh:.1f} -> fill {target}): {Path(svg).name}")
            _progress()

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futures = [ex.submit(process, f) for f in svg_files]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                with lock:
                    errors += 1
                    note(f"UNHANDLED ERROR: {e}")
                    _progress()

    print(f"\n  Scaled {scaled} file(s)" + (f", {errors} error(s)" if errors else ""),
          flush=True)


# ── Phase 4: Clean with scour ─────────────────────────────────────────────────

_ORPHAN_PREFIXES = ['inkscape', 'sodipodi', 'sketch', 'xlink', 'osb']


def strip_orphan_namespaces(svg_file):
    """Remove namespace-prefixed attributes whose namespace is not declared."""
    with open(svg_file) as f:
        content = f.read()
    for prefix in _ORPHAN_PREFIXES:
        if f'xmlns:{prefix}=' not in content:
            content = re.sub(rf' {prefix}:[a-zA-Z_-]+="[^"]*"', '', content)
            content = re.sub(rf" {prefix}:[a-zA-Z_-]+='[^']*'", '', content)
    with open(svg_file, 'w') as f:
        f.write(content)


def clean_svg(svg_file):
    strip_orphan_namespaces(svg_file)

    r = subprocess.run(["xmllint", "--noout", svg_file],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, f"xml error after namespace strip"

    before = os.path.getsize(svg_file)
    with tempfile.NamedTemporaryFile(suffix='.svg', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        r = subprocess.run([
            "scour", "-i", svg_file, "-o", tmp_path,
            "--remove-descriptive-elements",
            "--enable-comment-stripping",
            "--strip-xml-prolog",
            "--enable-id-stripping",
            "--protect-ids-prefix=current-",
            "--indent=none",
            "--quiet",
        ], capture_output=True, text=True)

        if r.returncode != 0:
            return None, "scour failed"

        after = os.path.getsize(tmp_path)
        shutil.move(tmp_path, svg_file)
        return before, after
    except Exception as e:
        return None, str(e)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def phase_scour(svg_files):
    print("\n=== Cleaning SVGs with scour ===")
    total = len(svg_files)
    cleaned = skipped = size_before = size_after = 0

    for i, svg in enumerate(svg_files, 1):
        before, after = clean_svg(svg)
        if before is None:
            skipped += 1
        else:
            size_before += before
            size_after += after
            cleaned += 1
        progress(i, total)

    print()
    return cleaned, skipped, size_before, size_after


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    signal.signal(signal.SIGINT,
                  lambda *_: (print("\n\nInterrupted."), sys.exit(130)))

    parser = argparse.ArgumentParser(
        prog='cleanup-svgs.py',
        description='Validate, fix, and optimize SVG files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ./cleanup-svgs.py Catalina-light/actions/22/\n"
            "  ./cleanup-svgs.py --check Catalina-dark/\n"
            "  ./cleanup-svgs.py --fix-size --scale-up Catalina-dark/status/16/\n"
            "  ./cleanup-svgs.py Catalina-light/apps/scalable/myapp.svg"
        ),
    )
    parser.add_argument('target', help='Directory or SVG file to process')
    parser.add_argument('--check',     action='store_true',
                        help='Validate XML only, do not modify files')
    parser.add_argument('--fix-size',  action='store_true',
                        help='Remove invisible rects and fix SVG dimensions to match target')
    parser.add_argument('--scale-up',  action='store_true',
                        help='Scale up undersized drawings to fill icon canvas (needs inkscape)')
    args = parser.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"Error: '{target}' is not a file or directory")
        sys.exit(1)

    for cmd in ['xmllint', 'scour']:
        if not shutil.which(cmd):
            print(f"Error: '{cmd}' is not installed")
            sys.exit(1)
    if args.scale_up and not shutil.which('inkscape'):
        print("Error: 'inkscape' is required for --scale-up")
        sys.exit(1)

    if target.is_file():
        if target.suffix != '.svg':
            print(f"Error: '{target}' is not an SVG file")
            sys.exit(1)
        svg_files = [str(target)]
    else:
        svg_files = sorted(str(p) for p in target.rglob('*.svg'))

    total = len(svg_files)
    if total == 0:
        print(f"No SVG files found in '{target}'")
        sys.exit(0)

    print(f"Found {total} SVG file(s) in '{target}'")

    # Phase 1: Validate
    xml_errors = phase_validate(svg_files)

    if args.check:
        print(f"\n=== Check complete ===")
        print(f"Total: {total} files, {len(xml_errors)} error(s)")
        sys.exit(1 if xml_errors else 0)

    valid_files = [f for f in svg_files if f not in xml_errors]
    if xml_errors:
        print(f"Skipping {len(xml_errors)} file(s) with XML errors during clean.")

    # Phase 2: Fix size
    if args.fix_size:
        phase_fix_size(valid_files)

    # Phase 3: Scale up
    if args.scale_up:
        jobs = os.cpu_count() or 4
        phase_scale_up(valid_files, jobs)

    # Phase 4: Scour
    cleaned, skipped, size_before, size_after = phase_scour(valid_files)
    saved = size_before - size_after

    print(f"\n=== Done ===")
    print(f"Total files:  {total}")
    print(f"Cleaned:      {cleaned}")
    print(f"Skipped:      {skipped}")
    print(f"Size before:  {human_size(size_before)}")
    print(f"Size after:   {human_size(size_after)}")
    print(f"Saved:        {human_size(saved)}")


if __name__ == '__main__':
    main()
