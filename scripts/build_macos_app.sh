#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=${0:A:h}
PROJECT_ROOT=${SCRIPT_DIR:h}
PYTHON_BIN=${PYTHON_BIN:-"$PROJECT_ROOT/.venv/bin/python"}
HSAS_BIN="$PROJECT_ROOT/.venv/bin/hsas"
OUTPUT_ROOT=${HIQS_APP_OUTPUT_DIR:-"$PROJECT_ROOT/dist"}
APP_ROOT="$OUTPUT_ROOT/HIQS.app"
CONTENTS_ROOT="$APP_ROOT/Contents"
VERSION=$(
  "$PYTHON_BIN" -c 'from hsas import __version__; print(__version__)'
)

if [[ "$(uname -s)" != "Darwin" ]]; then
  print -u2 "HIQS.app can only be built on macOS."
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" || ! -x "$HSAS_BIN" ]]; then
  print -u2 "Project environment not found. Create $PROJECT_ROOT/.venv and install HIQS first."
  exit 1
fi
if [[ ! -f "$PROJECT_ROOT/pyproject.toml" ]]; then
  print -u2 "HIQS project root not found: $PROJECT_ROOT"
  exit 1
fi

rm -rf "$APP_ROOT"
mkdir -p "$CONTENTS_ROOT/MacOS" "$CONTENTS_ROOT/Resources"
cp "$PROJECT_ROOT/packaging/macos/Info.plist" "$CONTENTS_ROOT/Info.plist"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$CONTENTS_ROOT/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${VERSION//./}" "$CONTENTS_ROOT/Info.plist"
/usr/libexec/PlistBuddy -c "Add :HIQSProjectRoot string $PROJECT_ROOT" "$CONTENTS_ROOT/Info.plist"

/usr/bin/swiftc \
  -framework AppKit -framework WebKit \
  "$PROJECT_ROOT/packaging/macos/HIQSApp.swift" \
  -o "$CONTENTS_ROOT/MacOS/HIQS"

chmod 755 "$CONTENTS_ROOT/MacOS/HIQS"
/usr/bin/codesign --force --sign - "$APP_ROOT"

print "Built $APP_ROOT"
print "Open it with: open '$APP_ROOT'"
print "The app uses the environment at: $PROJECT_ROOT/.venv"
