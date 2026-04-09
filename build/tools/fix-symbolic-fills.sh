#!/bin/bash
#
# fix-symbolic-fills.sh — Fix symbolic icons to use ColorScheme-Text + currentColor
#
# Ensures all symbolic/action icons use the proper ColorScheme pattern
# so desktop environments can recolor them.
#
# Usage:
#   ./fix-symbolic-fills.sh <directory>
#
# Examples:
#   ./fix-symbolic-fills.sh Catalina-dark/actions/16
#   ./fix-symbolic-fills.sh Catalina-light/actions/16

set -euo pipefail

TARGET="${1:?Usage: $0 <directory>}"

if [[ ! -d "$TARGET" ]]; then
    echo "Error: '$TARGET' is not a directory"
    exit 1
fi

# Determine the theme color based on dark/light variant
if [[ "$TARGET" == *dark* ]]; then
    TEXT_COLOR="#bebebe"
    HIGHLIGHT_COLOR="#3daee9"
else
    TEXT_COLOR="#5c616c"
    HIGHLIGHT_COLOR="#5294e2"
fi

STYLE_BLOCK="<defs>\n<style id=\"current-color-scheme\" type=\"text/css\">.ColorScheme-Text {\n        color:${TEXT_COLOR};\n      }</style>\n</defs>"

# Monochrome fill colors that should become currentColor
# These are the various white/gray/dark fills used for the icon "body"
MONO_FILLS='#f1f8f8|#f1f6f8|#f4f5f5|#dedede|#bebebe|#555555|#555|#fff|#ffffff|#1a1a1a|#eff0f1|#31363b'

CAT2_FIXED=0
CAT1_FIXED=0
SKIPPED=0

mapfile -t SVG_FILES < <(find "$TARGET" -maxdepth 1 -type f -name '*.svg' | sort)
TOTAL=${#SVG_FILES[@]}

echo "Found $TOTAL SVG files in '$TARGET'"
echo "Theme text color: $TEXT_COLOR"
echo ""

for svg in "${SVG_FILES[@]}"; do
    # Category 2: has ColorScheme-Text class but hardcoded fill (not currentColor)
    if grep -q 'ColorScheme-Text' "$svg" && ! grep -q 'currentColor' "$svg"; then
        # Replace hardcoded fill on elements that have ColorScheme-Text class
        # Match: class="ColorScheme-Text" ... fill="<color>" (on same element/line)
        sed -i -E "s/(class=\"ColorScheme-Text\"[^>]*) fill=\"[^\"]+\"/\1 fill=\"currentColor\"/g" "$svg"
        # Also match reversed order: fill="<color>" ... class="ColorScheme-Text"
        sed -i -E "s/fill=\"[^\"]+\"([^>]* class=\"ColorScheme-Text\")/fill=\"currentColor\"\1/g" "$svg"
        CAT2_FIXED=$((CAT2_FIXED + 1))
        continue
    fi

    # Category 1: completely missing ColorScheme pattern
    if ! grep -q 'ColorScheme-Text' "$svg" && ! grep -q 'currentColor' "$svg"; then
        # Skip icons that only use colored/accent fills (not monochrome)
        if ! grep -qP "fill=\"(${MONO_FILLS})\"" "$svg"; then
            SKIPPED=$((SKIPPED + 1))
            continue
        fi

        # Add class="ColorScheme-Text" and fill="currentColor" to shape elements with monochrome fills
        sed -i -E "s/<(path|rect|circle|ellipse|polygon|polyline|line)([^>]*) fill=\"(${MONO_FILLS})\"/<\1\2 class=\"ColorScheme-Text\" fill=\"currentColor\"/g" "$svg"
        # Handle fill before other attributes too
        sed -i -E "s/<(path|rect|circle|ellipse|polygon|polyline|line) fill=\"(${MONO_FILLS})\"/<\1 class=\"ColorScheme-Text\" fill=\"currentColor\"/g" "$svg"

        # Remove monochrome fill from <g> elements (children with currentColor override it)
        sed -i -E "s/(<g[^>]*) fill=\"(${MONO_FILLS})\"/\1/g" "$svg"

        # Add <defs><style> block after the opening <svg...> tag if not present
        if ! grep -q 'current-color-scheme' "$svg"; then
            sed -i "s|<svg\([^>]*\)>|<svg\1>\n${STYLE_BLOCK}|" "$svg"
        fi

        CAT1_FIXED=$((CAT1_FIXED + 1))
        continue
    fi
done

echo "=== Done ==="
echo "Total files:      $TOTAL"
echo "Cat 2 fixed:      $CAT2_FIXED  (had class, added currentColor)"
echo "Cat 1 fixed:      $CAT1_FIXED  (added full ColorScheme pattern)"
echo "Skipped:          $SKIPPED  (non-monochrome / accent-only icons)"
echo "Already correct:  $((TOTAL - CAT2_FIXED - CAT1_FIXED - SKIPPED))"
