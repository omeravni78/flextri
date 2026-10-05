#!/usr/bin/env bash
# Wrap dist/flexTri.app in a .dmg with an Applications shortcut to drag it onto.
# Usage: packaging/macos/build_dmg.sh OUTPUT.dmg
set -euo pipefail
out="$1"
stage="$(mktemp -d)"
cp -R dist/flexTri.app "$stage/"
ln -s /Applications "$stage/Applications"
hdiutil create -volname flexTri -srcfolder "$stage" -ov -format UDZO "$out"
rm -rf "$stage"
