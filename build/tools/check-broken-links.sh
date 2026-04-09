#!/bin/bash
#
# check-broken-links.sh — Find broken symlinks in a directory
#
# Usage:
#   ./check-broken-links.sh [OPTIONS] <directory>
#
# Options:
#   --help     Show this help message
#
# Examples:
#   ./check-broken-links.sh Catalina-light/
#   ./check-broken-links.sh Catalina-dark/128x128/apps/

set -euo pipefail

usage() {
    sed -n '3,13p' "$0" | sed 's/^# \?//'
    exit 0
}

TARGET_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage ;;
        -*) echo "Error: Unknown option '$1'"; usage ;;
        *)
            if [[ -z "$TARGET_DIR" ]]; then
                TARGET_DIR="$1"
            else
                echo "Error: Multiple directories specified"
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$TARGET_DIR" ]]; then
    echo "Error: No directory specified"
    usage
fi

if [[ ! -d "$TARGET_DIR" ]]; then
    echo "Error: '$TARGET_DIR' is not a directory"
    exit 1
fi

COUNT=0

while IFS= read -r -d '' link; do
    target=$(readlink "$link")
    echo "$link -> $target"
    COUNT=$((COUNT + 1))
done < <(find "$TARGET_DIR" -xtype l -print0 | sort -z)

if [[ $COUNT -eq 0 ]]; then
    echo "No broken symlinks found in '$TARGET_DIR'"
else
    echo ""
    echo "Found $COUNT broken symlink(s)"
fi

exit $(( COUNT > 0 ? 1 : 0 ))
