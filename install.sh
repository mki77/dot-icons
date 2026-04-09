#!/bin/bash

name=ToDo
target="$HOME/.local/share/icons/$name"

echo "Installing icon theme..."
set -e
mkdir -p "$target"
rsync -av scalable/ "$target/" --del
rsync -av symbolic/ "$target/"
gtk-update-icon-cache -f "$target"
exit 0

