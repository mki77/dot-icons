#!/usr/bin/env python3
"""
add-symbolic-suffix.py — Append '-symbolic' to SVG filenames that are missing it

Renames every *.svg file in the target folder whose name does not already end
with '-symbolic.svg', then updates any symlink targets that were also renamed.
Finally, attempts to repair any broken symlinks left behind by following a
reference folder chain (e.g. a paired Catalina-light/ or Catalina-dark/ tree).

Usage:
  ./add-symbolic-suffix.py [OPTIONS] <folder>

Options:
  --dry-run        Print what would be done without making any changes
  --ref-folder     Path to a reference folder to look up correct targets for
                   broken symlinks (e.g. the equivalent folder in the other theme)
  --help           Show this help message

Examples:
  ./add-symbolic-suffix.py Catalina-dark/actions/symbolic/
  ./add-symbolic-suffix.py --dry-run Catalina-dark/status/symbolic/
  ./add-symbolic-suffix.py --ref-folder Catalina-light/actions/symbolic/ Catalina-dark/actions/symbolic/
"""

import argparse
import os
import sys


def build_rename_map(folder):
    """Return {old_name: new_name} for every .svg lacking -symbolic suffix."""
    rename_map = {}
    for name in os.listdir(folder):
        if name.endswith(".svg") and not name.endswith("-symbolic.svg"):
            stem = name[:-4]
            rename_map[name] = stem + "-symbolic.svg"
    return rename_map


def rename_regular_files(folder, rename_map, dry_run):
    """Rename non-symlink files first so symlinks can still resolve."""
    regular = [n for n in rename_map
                if not os.path.islink(os.path.join(folder, n))]
    for name in regular:
        old = os.path.join(folder, name)
        new = os.path.join(folder, rename_map[name])
        if dry_run:
            print(f"  rename  {name}  ->  {rename_map[name]}")
        else:
            os.rename(old, new)
    return len(regular)


def rename_symlinks(folder, rename_map, dry_run):
    """Rename symlinks, updating their targets if those were also renamed.

    When a symlink's new name would collide with an already-existing file
    (meaning the real file was the authoritative copy), the symlink is simply
    removed — the real file acts as the canonical entry.
    """
    symlinks = [n for n in rename_map
                if os.path.islink(os.path.join(folder, n))]
    renamed = skipped = 0
    for name in symlinks:
        old_link = os.path.join(folder, name)
        old_target = os.readlink(old_link)
        new_name = rename_map[name]
        new_link = os.path.join(folder, new_name)

        # Rewrite target if it is a flat (same-dir) name that was also renamed
        if "/" not in old_target and old_target in rename_map:
            new_target = rename_map[old_target]
        else:
            new_target = old_target

        if os.path.exists(new_link) or os.path.islink(new_link):
            # New name already occupied — the canonical file is already there
            if dry_run:
                print(f"  skip    {name}  (target name {new_name!r} already exists)")
            else:
                os.unlink(old_link)
            skipped += 1
        else:
            if dry_run:
                print(f"  symlink {name} -> {old_target}  =>  {new_name} -> {new_target}")
            else:
                os.symlink(new_target, new_link)
                os.unlink(old_link)
            renamed += 1
    return renamed, skipped


def find_broken_symlinks(folder):
    broken = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.islink(path) and not os.path.exists(path):
            broken.append((name, os.readlink(path)))
    return broken


def fix_self_referencing(folder, dry_run, ref_folder=None):
    """Fix symlinks whose target resolves to themselves or is missing.

    Strategy:
      1. If the target ends with '-symbolic-symbolic.svg', trim to '-symbolic.svg'.
      2. If the target is a plain foo.svg that no longer exists but foo-symbolic.svg
         does, update to foo-symbolic.svg.
      3. If a ref_folder is given, look up the original target chain there and
         follow it to the renamed equivalent.
    """
    fixed = unfixed = 0
    for name, raw_target in find_broken_symlinks(folder):
        path = os.path.join(folder, name)

        # Strip ./ prefix for resolution
        prefix = "./" if raw_target.startswith("./") else ""
        clean_target = raw_target[len(prefix):]

        # Skip non-flat targets (cross-directory links not handled here)
        if "/" in clean_target:
            unfixed += 1
            continue

        new_clean = None

        # Case 1: double -symbolic suffix from the rename
        if clean_target.endswith("-symbolic-symbolic.svg"):
            candidate = clean_target[:-len("-symbolic-symbolic.svg")] + "-symbolic.svg"
            if os.path.exists(os.path.join(folder, candidate)) or \
               os.path.islink(os.path.join(folder, candidate)):
                new_clean = candidate

        # Case 2: target was a plain foo.svg that got renamed to foo-symbolic.svg
        if new_clean is None and clean_target.endswith(".svg") \
                and not clean_target.endswith("-symbolic.svg"):
            candidate = clean_target[:-4] + "-symbolic.svg"
            if os.path.exists(os.path.join(folder, candidate)) or \
               os.path.islink(os.path.join(folder, candidate)):
                new_clean = candidate

        # Case 3: use ref_folder to trace the original chain one level down
        if new_clean is None and ref_folder:
            # The ref name is the -symbolic.svg stripped of suffix, pointing to
            # the un-suffixed file in the reference folder
            stem = name[:-len("-symbolic.svg")] if name.endswith("-symbolic.svg") \
                   else name[:-4]
            ref_name = stem + ".svg"
            ref_path = os.path.join(ref_folder, ref_name)
            if os.path.islink(ref_path):
                ref_target = os.readlink(ref_path)
                ref_prefix = "./" if ref_target.startswith("./") else ""
                ref_clean = ref_target[len(ref_prefix):]
                if "/" not in ref_clean and ref_clean.endswith(".svg"):
                    # Map the ref target to the renamed equivalent in our folder
                    if ref_clean.endswith("-symbolic.svg"):
                        candidate = ref_clean
                    else:
                        candidate = ref_clean[:-4] + "-symbolic.svg"
                    if os.path.exists(os.path.join(folder, candidate)) or \
                       os.path.islink(os.path.join(folder, candidate)):
                        new_clean = ref_prefix + candidate

        if new_clean is not None:
            new_target = prefix + new_clean
            if dry_run:
                print(f"  fix     {name} -> {raw_target}  =>  {new_target}")
            else:
                os.unlink(path)
                os.symlink(new_target, path)
            fixed += 1
        else:
            print(f"  WARNING: cannot fix broken symlink: {name} -> {raw_target}")
            unfixed += 1

    return fixed, unfixed


def main():
    parser = argparse.ArgumentParser(
        description="Append '-symbolic' suffix to SVG icon filenames.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("folder", help="Folder to process")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show changes without applying them")
    parser.add_argument("--ref-folder", metavar="PATH",
                        help="Reference folder for resolving broken symlinks")
    args = parser.parse_args()

    folder = os.path.realpath(args.folder)
    if not os.path.isdir(folder):
        sys.exit(f"Error: not a directory: {args.folder}")

    ref_folder = None
    if args.ref_folder:
        ref_folder = os.path.realpath(args.ref_folder)
        if not os.path.isdir(ref_folder):
            sys.exit(f"Error: ref-folder is not a directory: {args.ref_folder}")

    print(f"Folder : {folder}")
    if args.dry_run:
        print("Mode   : dry-run (no changes will be made)")
    if ref_folder:
        print(f"Ref    : {ref_folder}")
    print()

    rename_map = build_rename_map(folder)
    if not rename_map:
        print("Nothing to rename — all SVGs already have '-symbolic' suffix.")
        return

    print(f"Files to rename: {len(rename_map)}")

    # Step 1: rename regular files
    n_regular = rename_regular_files(folder, rename_map, args.dry_run)
    print(f"  Regular files renamed : {n_regular}")

    # Step 2: rename symlinks
    n_renamed, n_skipped = rename_symlinks(folder, rename_map, args.dry_run)
    print(f"  Symlinks renamed      : {n_renamed}")
    print(f"  Symlinks skipped      : {n_skipped} (target name already existed)")
    print()

    # Step 3: fix any broken symlinks
    broken_before = find_broken_symlinks(folder)
    if broken_before:
        print(f"Broken symlinks to fix: {len(broken_before)}")
        n_fixed, n_unfixed = fix_self_referencing(folder, args.dry_run, ref_folder)
        print(f"  Fixed   : {n_fixed}")
        if n_unfixed:
            print(f"  Unfixed : {n_unfixed}  (see WARNINGs above)")
    else:
        print("No broken symlinks.")

    if not args.dry_run:
        remaining = find_broken_symlinks(folder)
        if remaining:
            print(f"\nWARNING: {len(remaining)} broken symlink(s) still remain:")
            for name, tgt in remaining:
                print(f"  {name} -> {tgt}")
        else:
            print("\nDone. No broken symlinks.")


if __name__ == "__main__":
    main()
