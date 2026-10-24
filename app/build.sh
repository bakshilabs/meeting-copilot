#!/bin/zsh
# Builds "Meeting Copilot.app" into ~/Applications.
set -e
cd "${0:A:h}/.."
APP="$HOME/Applications/Meeting Copilot.app"
B=$(mktemp -d)
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -swift-version 5 app/Launcher.swift -o "$APP/Contents/MacOS/MeetingCopilot"
mkdir "$B/icon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s app/icon-1024.png --out "$B/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) app/icon-1024.png --out "$B/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$B/icon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Meeting Copilot</string>
  <key>CFBundleDisplayName</key><string>Meeting Copilot</string>
  <key>CFBundleIdentifier</key><string>com.bakshilabs.meetingcopilot</string>
  <key>CFBundleExecutable</key><string>MeetingCopilot</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>15.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Meeting Copilot transcribes what you say in meetings.</string>
  <key>NSScreenCaptureUsageDescription</key><string>Meeting Copilot listens to call audio from Teams, Meet and Zoom.</string>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>CopilotProjectDir</key><string>$PWD</string>
</dict></plist>
PLIST
codesign --force --deep -s - "$APP"
rm -rf "$B"
echo "Built $APP"
