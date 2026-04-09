#!/bin/bash
#
# recolor-svg.sh — Replace a fill color in SVG files
#
# Usage:
#   ./recolor-svg.sh <old-color> <new-color> <file.svg | directory>
#
# Examples:
#   ./recolor-svg.sh "#202020" "#ffffff" icon.svg
#   ./recolor-svg.sh "#202020" "#ffffff" Catalina-dark/actions/22/

set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 <old-color> <new-color> <file.svg | directory>"
    exit 1
fi

OLD="$1"
NEW="$2"
TARGET="$3"

recolor_file() {
    local file="$1"
    if grep -q "$OLD" "$file"; then
        sed -i "s/$OLD/$NEW/g" "$file"
        echo "Updated: $file"
    fi
}

if [[ -f "$TARGET" ]]; then
    recolor_file "$TARGET"
elif [[ -d "$TARGET" ]]; then
    COUNT=0
    while IFS= read -r svg; do
        recolor_file "$svg" && :
        COUNT=$((COUNT + 1))
    done < <(grep -rl "$OLD" "$TARGET" --include='*.svg' | sort)
    echo ""
    echo "Updated $COUNT file(s)."
else
    echo "Error: '$TARGET' is not a file or directory"
    exit 1
fi
