#!/bin/zsh
# Build a signed LeanFile installer package (.pkg).
# Usage: ./make-pkg.sh [signing-identity-name]
#   Default identity: "LeanFile Signing" (self-signed, created on the
#   build machine). With a real Apple Developer ID in the keychain,
#   pass e.g. "Developer ID Application: ... (TEAMID)" and the pkg
#   signer "Developer ID Installer: ...".
set -e
cd "$(dirname "$0")/.."
APP_IDENTITY="${1:-LeanFile Signing}"
PKG_IDENTITY="${2:-$APP_IDENTITY}"
VERSION=0.1.0
WORK=$(mktemp -d)

./build.sh
APP=build/LeanFile.app

echo "== signing app with: $APP_IDENTITY"
codesign --force --deep --options runtime --sign "$APP_IDENTITY" "$APP" || \
  echo "WARN: app codesign failed (identity missing?), continuing unsigned"
codesign -dvv "$APP" 2>&1 | grep -E "Authority|Signature" | head -3 || true

mkdir -p "$WORK/root/Applications"
cp -R "$APP" "$WORK/root/Applications/"

mkdir -p "$WORK/scripts"
cp packaging/postinstall "$WORK/scripts/"
chmod +x "$WORK/scripts/postinstall"

pkgbuild \
  --root "$WORK/root" \
  --scripts "$WORK/scripts" \
  --identifier tech.mm1031.leanfile \
  --version "$VERSION" \
  --install-location / \
  "$WORK/component.pkg"

OUT="$HOME/Desktop/LeanFile-$VERSION.pkg"
if productsign --sign "$PKG_IDENTITY" "$WORK/component.pkg" "$OUT" 2>/dev/null; then
  echo "== pkg signed with: $PKG_IDENTITY"
else
  echo "WARN: productsign failed; shipping unsigned pkg"
  cp "$WORK/component.pkg" "$OUT"
fi
pkgutil --check-signature "$OUT" || true
echo "BUILT $OUT"
shasum -a 256 "$OUT"
