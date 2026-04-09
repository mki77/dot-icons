#!/usr/bin/env python3
"""
Flatten translate() transforms in symbolic SVG icons.

GTK4's simplified SVG renderer cannot handle translate() transforms with
large offset values — it parses the SVG without error but renders invisibly.
This script removes the <g transform="translate(dx dy)"> wrapper and applies
the offset directly to all child element coordinates.

Handles: <path>, <rect>, <circle>, <ellipse>, <line>, <polygon>, <polyline>

Usage:
    python3 flatten-svg-transforms.py <file_or_directory> [...]

Examples:
    python3 flatten-svg-transforms.py icon.svg
    python3 flatten-svg-transforms.py Catalina-light/devices/symbolic/
    python3 flatten-svg-transforms.py Catalina-light/*/symbolic/
"""

import re
import sys
import os
import glob
import xml.etree.ElementTree as ET


SVG_NS = 'http://www.w3.org/2000/svg'
# Register namespace so output doesn't get ns0: prefixes
ET.register_namespace('', SVG_NS)


def parse_translate(transform_str):
    """Extract dx, dy from translate(dx dy) or translate(dx, dy)."""
    NUM = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?'
    m = re.search(rf'translate\(\s*({NUM})\s*[,\s]\s*({NUM})\s*\)', transform_str, re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def fmt(n):
    """Format number compactly: drop trailing zeros."""
    if n == int(n) and abs(n) < 1e10:
        return str(int(n))
    return f"{n:g}"


def tokenize_svg_numbers(s):
    """Extract SVG numbers from a string, handling cases like '423.97-224.53'."""
    return re.findall(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?', s, re.IGNORECASE)


def adjust_path_d(d_attr, dx, dy):
    """Apply translate to the first moveto of each subpath in SVG path data.

    In SVG path 'd' attribute:
    - The first 'm'/'M' command is always absolute
    - After 'z', the next 'm' is relative to the closed subpath's start
    - All other lowercase commands are relative (no adjustment needed)
    """
    if not d_attr or not d_attr.strip():
        return d_attr

    # We need to find and adjust the first moveto's absolute coordinates.
    # Strategy: find the leading m/M command and its first two numbers,
    # adjust them, leave everything else untouched.

    stripped = d_attr.strip()
    # Match: optional whitespace, m or M, then capture everything
    m = re.match(r'^([mM])', stripped)
    if not m:
        return d_attr

    cmd = m.group(1)
    rest = stripped[m.end():]

    # Extract the first two numbers (x, y of the moveto)
    nums = tokenize_svg_numbers(rest)
    if len(nums) < 2:
        return d_attr

    x_str = nums[0]
    y_str = nums[1]
    x_new = float(x_str) + dx
    y_new = float(y_str) + dy

    # Find where x_str and y_str are in 'rest' and replace them
    # Find position of first number
    x_match = re.search(re.escape(x_str), rest)
    if not x_match:
        return d_attr

    after_x = rest[x_match.end():]
    y_match = re.search(re.escape(y_str), after_x)
    if not y_match:
        return d_attr

    # Reconstruct: cmd + new_x + separator + new_y + remainder
    before_x = rest[:x_match.start()]
    between = after_x[:y_match.start()]
    after_y = after_x[y_match.end():]

    # Use space as separator if between is empty or just a sign boundary
    if not between.strip(' ,'):
        between = ' '

    new_d = f"{cmd}{before_x}{fmt(x_new)}{between}{fmt(y_new)}{after_y}"
    return new_d


def adjust_attr(element, attr, offset):
    """Adjust a numeric attribute by offset."""
    val = element.get(attr)
    if val is not None:
        try:
            element.set(attr, fmt(float(val) + offset))
        except ValueError:
            pass


def adjust_points(points_str, dx, dy):
    """Adjust all coordinate pairs in a points attribute (polygon/polyline)."""
    nums = tokenize_svg_numbers(points_str)
    if len(nums) < 2 or len(nums) % 2 != 0:
        return points_str
    pairs = []
    for i in range(0, len(nums), 2):
        x = float(nums[i]) + dx
        y = float(nums[i + 1]) + dy
        pairs.append(f"{fmt(x)},{fmt(y)}")
    return ' '.join(pairs)


def fold_translate_into_transform(el, dx, dy):
    """Fold a parent translate(dx,dy) into an element's existing transform.

    SVG applies parent transform after child transform, so for:
      parent: translate(dx, dy)  child: matrix(a,b,c,d,e,f)
    Combined = matrix(a, b, c, d, e+dx, f+dy)

    For child: translate(cx, cy) → translate(cx+dx, cy+dy)
    """
    transform = el.get('transform', '')

    # Check for matrix transform
    m = re.search(
        r'matrix\(\s*([^\s,]+)\s*[,\s]\s*([^\s,]+)\s*[,\s]\s*([^\s,]+)\s*[,\s]\s*([^\s,]+)\s*[,\s]\s*([^\s,]+)\s*[,\s]\s*([^\s,]+)\s*\)',
        transform)
    if m:
        a, b, c, d, e, f = [float(x) for x in m.groups()]
        new_matrix = f'matrix({fmt(a)} {fmt(b)} {fmt(c)} {fmt(d)} {fmt(e + dx)} {fmt(f + dy)})'
        el.set('transform', transform[:m.start()] + new_matrix + transform[m.end():])
        return

    # Check for translate transform
    NUM = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?'
    t = re.search(rf'translate\(\s*({NUM})\s*[,\s]\s*({NUM})\s*\)', transform, re.IGNORECASE)
    if t:
        cx, cy = float(t.group(1)), float(t.group(2))
        new_translate = f'translate({fmt(cx + dx)} {fmt(cy + dy)})'
        el.set('transform', transform[:t.start()] + new_translate + transform[t.end():])
        return

    # Unknown transform type — prepend a translate
    if transform.strip():
        el.set('transform', f'translate({fmt(dx)} {fmt(dy)}) {transform}')
    else:
        el.set('transform', f'translate({fmt(dx)} {fmt(dy)})')


def apply_translate_to_element(el, dx, dy):
    """Apply translate offset to a single SVG element's coordinates."""
    # If the element has its own transform, fold the translate into it
    # instead of adjusting coordinates (which would break the transform chain)
    if el.get('transform'):
        fold_translate_into_transform(el, dx, dy)
        return

    tag = el.tag
    # Strip namespace if present
    if tag.startswith('{'):
        tag = tag.split('}', 1)[1]

    if tag == 'path':
        d = el.get('d')
        if d:
            el.set('d', adjust_path_d(d, dx, dy))

    elif tag == 'rect':
        adjust_attr(el, 'x', dx)
        adjust_attr(el, 'y', dy)

    elif tag in ('circle', 'ellipse'):
        adjust_attr(el, 'cx', dx)
        adjust_attr(el, 'cy', dy)

    elif tag == 'line':
        adjust_attr(el, 'x1', dx)
        adjust_attr(el, 'y1', dy)
        adjust_attr(el, 'x2', dx)
        adjust_attr(el, 'y2', dy)

    elif tag in ('polygon', 'polyline'):
        pts = el.get('points')
        if pts:
            el.set('points', adjust_points(pts, dx, dy))

    elif tag == 'g':
        # Nested group without its own transform — adjust all children recursively
        for child in el:
            apply_translate_to_element(child, dx, dy)


def flatten_svg(filepath):
    """Flatten translate transforms in an SVG file. Returns True if modified."""
    if os.path.islink(filepath) and not os.path.exists(filepath):
        return False
    if not os.path.isfile(filepath):
        return False

    with open(filepath, 'r') as f:
        original = f.read()

    # Quick check before full parse
    if 'translate(' not in original:
        return False

    try:
        tree = ET.parse(filepath)
    except ET.ParseError:
        return False

    root = tree.getroot()
    modified = False

    # Find all elements with translate transforms
    for el in root.iter():
        transform = el.get('transform', '')
        offset = parse_translate(transform)
        if not offset:
            continue

        dx, dy = offset
        # Skip small offsets (already in viewport range)
        if abs(dx) < 20 and abs(dy) < 20:
            continue

        tag = el.tag
        if tag.startswith('{'):
            tag = tag.split('}', 1)[1]

        if tag == 'g':
            # Apply translate to all children
            for child in el:
                apply_translate_to_element(child, dx, dy)
        else:
            # Apply translate directly to this element
            apply_translate_to_element(el, dx, dy)

        # Remove the transform attribute
        del el.attrib['transform']
        modified = True

    if not modified:
        return False

    # Also normalize height to integer if close (16.009 -> 16)
    svg_height = root.get('height', '')
    try:
        h = float(svg_height)
        if h != int(h) and abs(h - round(h)) < 0.1:
            root.set('height', str(int(round(h))))
    except ValueError:
        pass

    # Write back — use ET to serialize, but we want compact output like the original
    # ET.write adds XML declaration and may reformat, so let's do minimal serialization
    ET.indent(tree, space='')
    output = ET.tostring(root, encoding='unicode', xml_declaration=False)

    # ET may add ns0 prefixes or change attribute order, so let's use a simpler approach:
    # Re-read the original and do targeted replacements instead.
    # Actually, let's just write the ET output and clean it up.

    # Remove any xmlns:ns0 artifacts
    output = output.replace('ns0:', '').replace(':ns0', '')

    # Ensure it ends with newline
    if not output.endswith('\n'):
        output += '\n'

    with open(filepath, 'w') as f:
        f.write(output)

    return True


def process_path(path):
    """Process a file or directory."""
    if os.path.isfile(path) and path.endswith('.svg'):
        return [(path, flatten_svg(path))]

    results = []
    if os.path.isdir(path):
        for svg in sorted(glob.glob(os.path.join(path, '**', '*.svg'), recursive=True)):
            results.append((svg, flatten_svg(svg)))
    return results


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    total_modified = 0
    total_skipped = 0

    for arg in sys.argv[1:]:
        paths = glob.glob(arg) if '*' in arg else [arg]
        for path in paths:
            results = process_path(path)
            for filepath, modified in results:
                if modified:
                    print(f"  fixed: {filepath}")
                    total_modified += 1
                else:
                    total_skipped += 1

    print(f"\nDone: {total_modified} fixed, {total_skipped} skipped")


if __name__ == '__main__':
    main()
