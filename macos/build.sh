#!/bin/zsh
# Build LeanFile.app (internal codename MM1031) with the Command Line Tools toolchain (no full Xcode).
set -e
cd "$(dirname "$0")"
SDK=$(xcrun --show-sdk-path)
APP=build/LeanFile.app
rm -rf build
mkdir -p $APP/Contents/MacOS
swiftc -O -sdk "$SDK" -target arm64-apple-macosx14.0 \
  -import-objc-header Sources/bridging.h \
  Sources/Database.swift Sources/L10n.swift Sources/App.swift \
  -lsqlite3 \
  -o $APP/Contents/MacOS/LeanFile
cp Info.plist $APP/Contents/Info.plist
mkdir -p $APP/Contents/Resources
[ -f avatar.jpg ] && cp avatar.jpg $APP/Contents/Resources/avatar.jpg
# App icon (LeanFile): build AppIcon.icns from icon-1024.png when possible.
if [ -f icon-1024.png ] && command -v iconutil >/dev/null 2>&1; then
  ICONSET=$(mktemp -d)/AppIcon.iconset
  mkdir -p "$ICONSET"
  for spec in "16:16x16" "32:16x16@2x" "32:32x32" "64:32x32@2x" "128:128x128" "256:128x128@2x" "256:256x256" "512:256x256@2x" "512:512x512" "1024:512x512@2x"; do
    px="${spec%%:*}"; nm="${spec##*:}"
    sips -z "$px" "$px" icon-1024.png --out "$ICONSET/icon_${nm}.png" >/dev/null 2>&1
  done
  mkdir -p $APP/Contents/Resources
  iconutil -c icns "$ICONSET" -o $APP/Contents/Resources/AppIcon.icns 2>/dev/null || true
fi
codesign --force --sign - $APP
echo "BUILT $APP"
