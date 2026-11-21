#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
APP_NAME="YouTube Downloader"
APP_BUNDLE="dist/${APP_NAME}.app"
DMG_PATH="$PWD/YouTubeDownloader.dmg"
STAGING="$PWD/dmg_staging"
ICON_PNG="$PWD/AppIcon.png"
ICONSET="$PWD/AppIcon.iconset"
ICON_ICNS="$PWD/AppIcon.icns"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ОШИБКА: сборку .app/.dmg нужно запускать на macOS."
  exit 1
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ОШИБКА: нужен Intel Mac (x86_64) для сборки под MacBook Pro 2017."
  exit 1
fi
command -v python3 >/dev/null 2>&1 || { echo "Не найден Python 3."; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "Не найден ffmpeg в PATH."; exit 1; }

FFMPEG_BIN="$(command -v ffmpeg)"
[[ -f "$ICON_PNG" ]] || { echo "Не найден AppIcon.png рядом с build.sh."; exit 1; }

# Создаём набор размеров macOS и собираем .icns.
rm -rf "$ICONSET" "$ICON_ICNS"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$ICON_ICNS"

rm -rf build dist dmg_staging .venv *.spec
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

pyinstaller \
  --noconfirm --clean --windowed --onedir \
  --name "$APP_NAME" \
  --icon "$ICON_ICNS" \
  --osx-bundle-identifier "local.youtube.downloader" \
  --target-architecture x86_64 \
  --collect-all yt_dlp \
  --collect-all yt_dlp_ejs \
  --collect-all flask \
  --collect-all werkzeug \
  --collect-all jinja2 \
  --collect-all certifi \
  --add-binary "$FFMPEG_BIN:." \
  youtube_app.py

[[ -d "$APP_BUNDLE" ]] || { echo "ОШИБКА: приложение не собрано."; exit 1; }
mkdir -p "$STAGING"
cp -R "$APP_BUNDLE" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
rm -f "$DMG_PATH"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" -ov -format UDZO "$DMG_PATH"
rm -rf "$STAGING" "$ICONSET"
echo "ГОТОВО: $DMG_PATH"
