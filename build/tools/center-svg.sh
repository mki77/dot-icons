#!/bin/bash
#
# center-svg.sh — Vertically center SVG icon content within its canvas
#
# Usage:
#   ./center-svg.sh <file.svg>        # single file
#   ./center-svg.sh <directory>        # all SVGs in directory (recursive)
#
# Requires: inkscape, imagemagick (magick)

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <file.svg | directory>"
    exit 1
fi

TMP=$(mktemp --suffix=.png)
trap 'rm -f "$TMP"' EXIT

center_file() {
    local FILE="$1"

    # Get canvas size from viewBox or width/height
    read -r VW VH <<< $(python3 -c "
import re
svg = open('$FILE').read()
m = re.search(r'viewBox=\"[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\"', svg)
if m:
    print(m.group(1), m.group(2))
else:
    w = re.search(r'width=\"([\d.]+)\"', svg)
    h = re.search(r'height=\"([\d.]+)\"', svg)
    print(w.group(1) if w else 128, h.group(1) if h else 128)
")

    # Render to PNG at canvas size
    inkscape "$FILE" --export-area-page --export-type=png \
        --export-filename="$TMP" --export-width="${VW%.*}" --export-height="${VH%.*}" 2>/dev/null

    # Measure visible content bounds and calculate vertical shift
    DY=$(magick "$TMP" -trim -format "%[fx:($VH-h)/2-page.y]" info:)

    if python3 -c "exit(0 if abs($DY) < 1 else 1)"; then
        return 0
    fi

    echo "Shifting by dy=$DY: $FILE"
    inkscape "$FILE" --batch-process \
        --actions="select-all;transform-translate:0,$DY;export-filename:$FILE;export-overwrite;export-do" 2>/dev/null
}

if [[ -f "$1" ]]; then
    center_file "$1"
elif [[ -d "$1" ]]; then
    COUNT=0
    SHIFTED=0
    while IFS= read -r svg; do
        COUNT=$((COUNT + 1))
        before_shift=$SHIFTED
        center_file "$svg" && :
        # Check if center_file printed a "Shifting" line
        if [[ $? -eq 0 ]]; then :; fi
    done < <(find "$1" -type f -name '*.svg' | sort)

    echo ""
    echo "Processed $COUNT files."
else
    echo "Error: '$1' is not a file or directory"
    exit 1
fi
