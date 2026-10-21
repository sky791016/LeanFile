#!/bin/zsh
# Build Guicang.app with the Command Line Tools toolchain (no full Xcode).
set -e
cd "$(dirname "$0")"
SDK=$(xcrun --show-sdk-path)
APP=build/Guicang.app
rm -rf build
mkdir -p $APP/Contents/MacOS
swiftc -O -sdk "$SDK" -target arm64-apple-macosx14.0 \
  -import-objc-header Sources/bridging.h \
  Sources/Database.swift Sources/L10n.swift Sources/App.swift \
  -lsqlite3 \
  -o $APP/Contents/MacOS/Guicang
cp Info.plist $APP/Contents/Info.plist
codesign --force --sign - $APP
echo "BUILT $APP"
