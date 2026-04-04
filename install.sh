#!/bin/sh

echo "Installing icon theme..."
iconame=Ashy
icodir=~/.icons
ln -s $icodir ~/.local/share/icons
rsync -a $iconame -t $icodir --del
rsync -a colors -t $icodir/$iconame --del
gtk-update-icon-cache -f $iconame
exit 0

