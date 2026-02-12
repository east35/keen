#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_PATH="$ROOT_DIR/dist/Keen.app"
README_PATH="$ROOT_DIR/marketing/README_FIRST.txt"
DMG_NAME="Keen.dmg"
DMG_PATH="$ROOT_DIR/$DMG_NAME"

if [ ! -d "$APP_PATH" ]; then
  echo "ERROR: $APP_PATH not found. Build the app first (bash scripts/build_macos.sh)." >&2
  exit 1
fi

if [ ! -f "$README_PATH" ]; then
  echo "ERROR: $README_PATH not found." >&2
  exit 1
fi

STAGING_DIR="$(mktemp -d -t keen-dmg-XXXXXXXX)"
cleanup() {
  rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

# Stage files
cp -R "$APP_PATH" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"
cp "$README_PATH" "$STAGING_DIR/README_FIRST.txt"

# Remove existing dmg if present
rm -f "$DMG_PATH"

# Create DMG
hdiutil create \
  -volname "Keen" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH" > /dev/null

echo "==> Created $DMG_PATH"
