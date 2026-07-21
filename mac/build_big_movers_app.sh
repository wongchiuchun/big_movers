#!/bin/zsh
set -euo pipefail

MAC_DIR=${0:A:h}
ROOT_DIR=${MAC_DIR:h}
SOURCE="$MAC_DIR/BigMovers.applescript"
APP_PATH="$ROOT_DIR/Big Movers.app"
EXISTING_ICON="$APP_PATH/Contents/Resources/applet.icns"
STAGE_DIR=$(mktemp -d /tmp/big-movers-app-build.XXXXXX)
STAGED_APP="$STAGE_DIR/Big Movers.app"

cleanup() {
  rm -rf -- "$STAGE_DIR"
}
trap cleanup EXIT INT TERM

[[ -f "$SOURCE" ]] || { print -u2 -- "AppleScript source missing: $SOURCE"; exit 1; }
[[ -f "$EXISTING_ICON" ]] || { print -u2 -- "Existing app icon missing: $EXISTING_ICON"; exit 1; }

osacompile -s -o "$STAGED_APP" "$SOURCE"
cp -p "$EXISTING_ICON" "$STAGED_APP/Contents/Resources/applet.icns"

plutil -replace CFBundleName -string "Big Movers" "$STAGED_APP/Contents/Info.plist"
plutil -replace OSAAppletStayOpen -bool true "$STAGED_APP/Contents/Info.plist"

[[ "$(plutil -extract CFBundleName raw "$STAGED_APP/Contents/Info.plist")" == "Big Movers" ]]
[[ "$(plutil -extract OSAAppletStayOpen raw "$STAGED_APP/Contents/Info.plist")" == "true" ]]

ditto "$STAGED_APP" "$APP_PATH"
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"

osadecompile "$APP_PATH/Contents/Resources/Scripts/main.scpt" | grep -q '^on quit$'
print -- "Built and verified: $APP_PATH"
