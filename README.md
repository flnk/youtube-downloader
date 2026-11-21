# YouTube Downloader

🇬🇧 English | [🇺🇦 Українська](README.uk.md)

A small desktop-style app for downloading videos or audio from YouTube.
It runs a local Flask server and opens a simple web UI in your browser.
Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/).

> The interface is in Ukrainian.

## Features

- Paste a link, fetch video info, choose quality (best, or a specific height such as 720p / 1080p)
- Download as **MP4** or audio only (**MP3**)
- Choose the destination folder (defaults to `Downloads`)
- Live download progress
- Packaged as a standalone **Windows `.exe`** and a **macOS `.app` / `.dmg`** with PyInstaller

## Tech stack

Python 3.11 · Flask · yt-dlp · ffmpeg · PyInstaller · GitHub Actions

## Run from source

Requires Python 3.11+ and [ffmpeg](https://ffmpeg.org/download.html) available in `PATH`.

```bash
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate
pip install -r requirements.txt
python youtube_app.py
```

Then open <http://127.0.0.1:5000> (it opens automatically).

## Build

### Windows `.exe` (GitHub Actions)

1. Open the **Actions** tab, choose **Build Windows EXE**, click **Run workflow**.
2. Download the `YouTube-Downloader-Windows` artifact. It contains `YouTube Downloader.exe`.

The workflow downloads ffmpeg itself, so `ffmpeg.exe` is not stored in the repository.

Or build locally (with ffmpeg.exe in the project folder):

```powershell
pyinstaller --noconfirm --clean --onefile --windowed `
  --name "YouTube Downloader" --icon "AppIcon.ico" `
  --collect-all yt_dlp --collect-all yt_dlp_ejs --collect-all flask `
  --collect-all werkzeug --collect-all jinja2 --collect-all certifi `
  --add-binary "ffmpeg.exe;." youtube_app.py
```

### macOS `.app` / `.dmg` (Intel)

Requires macOS on Intel (x86_64), Python 3 and ffmpeg in `PATH`:

```bash
chmod +x build.sh
./build.sh
```

Output: `YouTubeDownloader.dmg`.

## Notes

- Windows console encoding: the app forces UTF-8 on `stdout`/`stderr`, so Cyrillic text does not crash on `cp1252` consoles.
- For personal use. Make sure your use complies with YouTube's Terms of Service and applicable copyright law.
