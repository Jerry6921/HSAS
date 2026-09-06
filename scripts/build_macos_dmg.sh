#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=${0:A:h}
PROJECT_ROOT=${SCRIPT_DIR:h}
PYTHON_BIN=${PYTHON_BIN:-"$PROJECT_ROOT/.venv/bin/python"}
BUILD_ROOT="$PROJECT_ROOT/build/macos"
OUTPUT_ROOT="$PROJECT_ROOT/dist"
APP_ROOT="$OUTPUT_ROOT/HIQS.app"
CONTENTS_ROOT="$APP_ROOT/Contents"
RESOURCES_ROOT="$CONTENTS_ROOT/Resources"
BACKEND_OUTPUT="$BUILD_ROOT/pyinstaller"
PLAYWRIGHT_ROOT=${PLAYWRIGHT_BROWSERS_PATH:-"$HOME/Library/Caches/ms-playwright"}
VERSION=$(
  "$PYTHON_BIN" -c 'from hsas import __version__; print(__version__)'
)
ARCHITECTURE=$(uname -m)
DMG_PATH="$OUTPUT_ROOT/HIQS-${VERSION}-macOS-${ARCHITECTURE}.dmg"
SDK_PATH=""

if [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 "Python environment not found: $PYTHON_BIN"
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import PyInstaller' >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install -c "$PROJECT_ROOT/requirements.lock" -e "$PROJECT_ROOT[macos-build]"
fi

PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_ROOT" "$PYTHON_BIN" -m playwright install chromium

rm -rf "$BUILD_ROOT" "$APP_ROOT" "$DMG_PATH"
mkdir -p "$BUILD_ROOT" "$OUTPUT_ROOT" "$CONTENTS_ROOT/MacOS" "$RESOURCES_ROOT"

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name hiqs-backend \
  --distpath "$BACKEND_OUTPUT" \
  --workpath "$BUILD_ROOT/work" \
  --specpath "$BUILD_ROOT" \
  --collect-data hsas \
  --collect-all playwright \
  "$PROJECT_ROOT/packaging/macos/backend_entry.py"

cp -R "$BACKEND_OUTPUT/hiqs-backend" "$RESOURCES_ROOT/backend"
cp -R "$PLAYWRIGHT_ROOT" "$RESOURCES_ROOT/playwright-browsers"
cp "$PROJECT_ROOT/packaging/macos/Info.plist" "$CONTENTS_ROOT/Info.plist"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$CONTENTS_ROOT/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${VERSION//./}" "$CONTENTS_ROOT/Info.plist"

if [[ -d /Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk ]]; then
  SDK_PATH=/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk
fi
if [[ -n "$SDK_PATH" ]]; then
  /usr/bin/swiftc -sdk "$SDK_PATH" \
    -framework AppKit -framework WebKit \
    "$PROJECT_ROOT/packaging/macos/HIQSApp.swift" \
    -o "$CONTENTS_ROOT/MacOS/HIQS"
else
  /usr/bin/swiftc \
    -framework AppKit -framework WebKit \
    "$PROJECT_ROOT/packaging/macos/HIQSApp.swift" \
    -o "$CONTENTS_ROOT/MacOS/HIQS"
fi

chmod 755 "$CONTENTS_ROOT/MacOS/HIQS" "$RESOURCES_ROOT/backend/hiqs-backend"
codesign --force --deep --sign - "$APP_ROOT"

DMG_STAGE="$BUILD_ROOT/dmg-stage"
mkdir -p "$DMG_STAGE"
cp -R "$APP_ROOT" "$DMG_STAGE/HIQS.app"
ln -s /Applications "$DMG_STAGE/Applications"
hdiutil create \
  -volname "HIQS $VERSION" \
  -srcfolder "$DMG_STAGE" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

shasum -a 256 "$DMG_PATH"
print "Built $DMG_PATH"
