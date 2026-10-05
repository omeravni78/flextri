#!/usr/bin/env bash
# Turn dist/flexTri/ into one flexTri.AppImage file. Needs appimagetool on PATH
# (https://github.com/AppImage/appimagetool/releases). Usage: packaging/linux/build_appimage.sh OUTPUT.AppImage
set -euo pipefail
out="$1"
appdir="$(mktemp -d)/flexTri.AppDir"
mkdir -p "$appdir/usr/bin"
cp -R dist/flexTri/. "$appdir/usr/bin/"
cp packaging/build/flextri.png "$appdir/flextri.png"
cat > "$appdir/flextri.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=flexTri
Comment=Flexible triathlon coaching
Exec=flexTri
Icon=flextri
Categories=Sports;Utility;
Terminal=false
DESKTOP
cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
exec "$(dirname "$(readlink -f "$0")")/usr/bin/flexTri" "$@"
APPRUN
chmod +x "$appdir/AppRun"
ARCH=x86_64 appimagetool --no-appstream "$appdir" "$out"
