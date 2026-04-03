#!/bin/sh

echo "Installing icon theme..."
iconame=Ashy
icodir=~/.icons
#ln -s $icodir ~/.local/share/icons
rsync -a $iconame -t $icodir
rsync -a colors -t $icodir/$iconame
gtk-update-icon-cache -f $iconame
exit 0

