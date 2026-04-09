#!/bin/bash
#
# Fix broken symlinks in the icon theme.
#
# For each broken symlink:
#   1. Extract the target filename (basename of wherever the link points)
#   2. Search for a real file with that name, starting from the symlink's
#      own directory, then walking up parents until the theme root
#      (Catalina-light or Catalina-dark).
#   3. If found, repoint the symlink using a correct relative path.
#   4. If not found, report it as unfixable.
#
# Self-referencing symlinks (same basename pointing to a nonexistent path)
# are searched for in the *other* theme variant (dark<>light) and copied if
# a real file is found there, since the icon content should be identical.
#
# Runs multiple passes — fixing one symlink may unblock others that chain
# through it.
#
# Usage: ./fix-broken-symlinks.sh [--dry-run] [directory]

set -euo pipefail

DRY_RUN=false
SEARCH_DIR=""

for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN=true
    elif [[ -z "$SEARCH_DIR" ]]; then
        SEARCH_DIR="$arg"
    fi
done

if $DRY_RUN; then
    echo "=== DRY RUN — no changes will be made ==="
    echo
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -n "$SEARCH_DIR" ]]; then
    # Resolve to absolute path relative to cwd
    if [[ "$SEARCH_DIR" != /* ]]; then
        SEARCH_DIR="$(cd "$SEARCH_DIR" && pwd)"
    fi
else
    SEARCH_DIR="$REPO_ROOT"
fi

total_fixed=0
total_unfixed=0

# Resolve symlink chains: follow the target basenames until we get
# a name that isn't itself a broken symlink in the same directory.
resolve_target_basename() {
    local dir="$1"
    local target="$2"
    local self_name="$3"
    local seen=" $self_name "
    local bn

    bn="$(basename "$target")"

    # Walk the chain up to 10 hops
    for _ in $(seq 1 10); do
        local candidate="$dir/$bn"
        if [[ -L "$candidate" ]] && ! [[ -e "$candidate" ]]; then
            local next
            next="$(readlink "$candidate")"
            local next_bn
            next_bn="$(basename "$next")"

            # Cycle detection
            if [[ " $seen " == *" $next_bn "* ]]; then
                echo "$bn"
                return
            fi
            seen="$seen $bn "
            bn="$next_bn"
        else
            break
        fi
    done

    echo "$bn"
}

# Find target file by name, searching current dir then walking up to theme root.
# Excludes the broken link itself and other broken symlinks.
# Prefers same directory, then parent, etc.
find_target_in_theme() {
    local target_name="$1"
    local link_abs="$2"
    local start_dir="$3"
    local theme_root_abs="$4"
    local found=""
    local search_dir="$start_dir"

    while true; do
        while IFS= read -r -d '' candidate; do
            local cand_abs
            cand_abs="$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")"
            if [[ "$cand_abs" == "$link_abs" ]]; then
                continue
            fi
            found="$candidate"
            break
        done < <(find "$search_dir" -maxdepth 1 -name "$target_name" -not -xtype l -print0 2>/dev/null)

        if [[ -n "$found" ]]; then
            echo "$found"
            return 0
        fi

        # Stop at theme root
        if [[ "$search_dir" == "$theme_root_abs" ]]; then
            break
        fi

        search_dir="$(dirname "$search_dir")"

        # Safety: don't go above theme root
        if [[ "$search_dir" != "$theme_root_abs"* && "$search_dir" != "$theme_root_abs" ]]; then
            break
        fi
    done

    # Broader recursive search from theme root
    while IFS= read -r -d '' candidate; do
        local cand_abs
        cand_abs="$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")"
        if [[ "$cand_abs" == "$link_abs" ]]; then
            continue
        fi
        echo "$candidate"
        return 0
    done < <(find "$theme_root_abs" -name "$target_name" -not -xtype l -print0 2>/dev/null)

    return 1
}

# Compute relative path without resolving symlinks
relative_path() {
    local from="$1"  # directory
    local to="$2"    # file (absolute path)
    python3 -c "import os.path; print(os.path.relpath('$to', '$from'))"
}

# Process one broken symlink. Returns 0 if fixed, 1 if not.
process_link() {
    local link="$1"
    local raw_target
    raw_target="$(readlink "$link")"
    local link_dir
    link_dir="$(dirname "$link")"
    local link_basename
    link_basename="$(basename "$link")"
    local link_abs
    link_abs="$(cd "$link_dir" && pwd)/$link_basename"
    local link_dir_abs
    link_dir_abs="$(cd "$link_dir" && pwd)"

    # Resolve chains to get the ultimate target filename
    local target_name
    target_name="$(resolve_target_basename "$link_dir" "$raw_target" "$link_basename")"

    # Determine theme root
    local theme_root="" other_theme_root=""
    if [[ "$link" == *Catalina-light* ]]; then
        theme_root="$REPO_ROOT/Catalina-light"
        other_theme_root="$REPO_ROOT/Catalina-dark"
    elif [[ "$link" == *Catalina-dark* ]]; then
        theme_root="$REPO_ROOT/Catalina-dark"
        other_theme_root="$REPO_ROOT/Catalina-light"
    else
        echo "SKIP (unknown theme): $link"
        return 1
    fi

    local theme_root_abs
    theme_root_abs="$(cd "$theme_root" && pwd)"

    # Self-referencing: same basename, target doesn't exist in same directory
    if [[ "$link_basename" == "$target_name" ]]; then
        # First, try a broad in-theme search (the file may exist in another directory)
        local found
        if found="$(find_target_in_theme "$target_name" "$link_abs" "$link_dir_abs" "$theme_root_abs")"; then
            local new_target
            new_target="$(relative_path "$link_dir_abs" "$(cd "$(dirname "$found")" && pwd)/$(basename "$found")")"
            if $DRY_RUN; then
                echo "WOULD FIX (in-theme, different dir): $link"
                echo "    old: $raw_target"
                echo "    new: $new_target"
            else
                rm "$link"
                ln -s "$new_target" "$link"
                echo "FIXED (in-theme, different dir): $link -> $new_target"
            fi
            return 0
        fi

        # Try finding it in the other theme variant at the equivalent path
        local rel_from_theme="${link_abs#$theme_root_abs/}"
        local other_candidate="$other_theme_root/$rel_from_theme"

        if [[ -f "$other_candidate" ]] && ! [[ -L "$other_candidate" && ! -e "$other_candidate" ]]; then
            if [[ -L "$other_candidate" ]]; then
                # Working symlink in other theme — read its target and find equivalent in our theme
                local other_target other_target_name
                other_target="$(readlink "$other_candidate")"
                other_target_name="$(basename "$other_target")"
                local found
                if found="$(find_target_in_theme "$other_target_name" "$link_abs" "$link_dir_abs" "$theme_root_abs")"; then
                    local new_target
                    new_target="$(relative_path "$link_dir_abs" "$(cd "$(dirname "$found")" && pwd)/$(basename "$found")")"
                    if $DRY_RUN; then
                        echo "WOULD FIX (via other theme symlink): $link"
                        echo "    old: $raw_target"
                        echo "    new: $new_target"
                    else
                        rm "$link"
                        ln -s "$new_target" "$link"
                        echo "FIXED (via other theme symlink): $link -> $new_target"
                    fi
                    return 0
                fi
            fi
            # Real file in other theme — copy it
            if $DRY_RUN; then
                echo "WOULD COPY (from other theme): $other_candidate -> $link"
            else
                rm "$link"
                cp "$other_candidate" "$link"
                echo "COPIED (from other theme): $other_candidate -> $link"
            fi
            return 0
        fi

        # Try broader search in other theme
        local other_theme_abs
        other_theme_abs="$(cd "$other_theme_root" && pwd)"
        local other_found=""
        while IFS= read -r -d '' candidate; do
            if [[ -f "$candidate" ]] && ! [[ -L "$candidate" && ! -e "$candidate" ]]; then
                other_found="$candidate"
                break
            fi
        done < <(find "$other_theme_abs" -name "$target_name" -not -xtype l -print0 2>/dev/null)

        if [[ -n "$other_found" ]]; then
            if [[ -L "$other_found" ]]; then
                local other_target other_target_name
                other_target="$(readlink "$other_found")"
                other_target_name="$(basename "$other_target")"
                local found
                if found="$(find_target_in_theme "$other_target_name" "$link_abs" "$link_dir_abs" "$theme_root_abs")"; then
                    local new_target
                    new_target="$(relative_path "$link_dir_abs" "$(cd "$(dirname "$found")" && pwd)/$(basename "$found")")"
                    if $DRY_RUN; then
                        echo "WOULD FIX (via other theme): $link"
                        echo "    old: $raw_target"
                        echo "    new: $new_target"
                    else
                        rm "$link"
                        ln -s "$new_target" "$link"
                        echo "FIXED (via other theme): $link -> $new_target"
                    fi
                    return 0
                fi
            fi
            if $DRY_RUN; then
                echo "WOULD COPY (from other theme): $other_found -> $link"
            else
                rm "$link"
                cp "$other_found" "$link"
                echo "COPIED (from other theme): $other_found -> $link"
            fi
            return 0
        fi

        echo "NOT FOUND: $link -> $raw_target (self-ref, not in other theme either)"
        return 1
    fi

    # Normal case: search within the same theme
    local found
    if found="$(find_target_in_theme "$target_name" "$link_abs" "$link_dir_abs" "$theme_root_abs")"; then
        local found_abs
        found_abs="$(cd "$(dirname "$found")" && pwd)/$(basename "$found")"
        local new_target
        new_target="$(relative_path "$link_dir_abs" "$found_abs")"

        if $DRY_RUN; then
            echo "WOULD FIX: $link"
            echo "    old: $raw_target"
            echo "    new: $new_target"
        else
            rm "$link"
            ln -s "$new_target" "$link"
            echo "FIXED: $link -> $new_target"
        fi
        return 0
    else
        echo "NOT FOUND: $link -> $raw_target (looking for '$target_name')"
        return 1
    fi
}

# Multi-pass: keep running until no more progress is made.
# Fixing one link (e.g. copying from other theme) can unblock others that chain through it.
pass=0
while true; do
    ((pass++)) || true
    fixed_this_pass=0
    unfixed_this_pass=0

    if [[ $pass -gt 1 ]]; then
        echo
        echo "--- Pass $pass ---"
    fi

    broken_count=$(find "$SEARCH_DIR" -xtype l -print0 | tr -cd '\0' | wc -c)
    if [[ "$broken_count" -eq 0 ]]; then
        break
    fi

    while IFS= read -r -d '' link; do
        if process_link "$link"; then
            ((fixed_this_pass++)) || true
        else
            ((unfixed_this_pass++)) || true
        fi
    done < <(find "$SEARCH_DIR" -xtype l -print0)

    total_fixed=$((total_fixed + fixed_this_pass))

    # Stop if no progress was made this pass
    if [[ $fixed_this_pass -eq 0 ]]; then
        total_unfixed=$unfixed_this_pass
        break
    fi

    # In dry-run mode, only one pass makes sense since nothing actually changes
    if $DRY_RUN; then
        total_unfixed=$unfixed_this_pass
        break
    fi
done

echo
echo "=== Summary ==="
echo "Passes:   $pass"
echo "Fixed:    $total_fixed"
echo "Unfixed:  $total_unfixed"
echo "Total:    $((total_fixed + total_unfixed))"
