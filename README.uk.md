# YouTube Downloader

[🇬🇧 English](README.md) | 🇺🇦 Українська

Невеликий застосунок для завантаження відео або аудіо з YouTube.
Запускає локальний сервер Flask і відкриває простий веб-інтерфейс у браузері.
Працює на основі [yt-dlp](https://github.com/yt-dlp/yt-dlp) та [ffmpeg](https://ffmpeg.org/).

> Інтерфейс застосунку українською мовою.

## Можливості

- Вставте посилання, отримайте інформацію про відео та оберіть якість (найкраща або конкретна висота, наприклад 720p / 1080p)
- Завантаження як **MP4** або лише аудіо (**MP3**)
- Вибір папки збереження (за замовчуванням `Downloads`)
- Відображення прогресу завантаження в реальному часі
- Збірка у вигляді окремого **Windows `.exe`** та **macOS `.app` / `.dmg`** за допомогою PyInstaller

## Технології

Python 3.11 · Flask · yt-dlp · ffmpeg · PyInstaller · GitHub Actions

## Запуск із вихідного коду

Потрібні Python 3.11+ та [ffmpeg](https://ffmpeg.org/download.html), доступний у `PATH`.

```bash
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate
pip install -r requirements.txt
python youtube_app.py
```

Після цього відкрийте <http://127.0.0.1:5000> (воно відкривається автоматично).

## Збірка

### Windows `.exe` (GitHub Actions)

1. Відкрийте вкладку **Actions**, оберіть **Build Windows EXE** і натисніть **Run workflow**.
2. Завантажте артефакт `YouTube-Downloader-Windows`. Усередині буде `YouTube Downloader.exe`.

Workflow сам завантажує ffmpeg, тому `ffmpeg.exe` у репозиторії не зберігається.

Або зберіть локально (з `ffmpeg.exe` у папці проєкту):

```powershell
pyinstaller --noconfirm --clean --onefile --windowed `
  --name "YouTube Downloader" --icon "AppIcon.ico" `
  --collect-all yt_dlp --collect-all yt_dlp_ejs --collect-all flask `
  --collect-all werkzeug --collect-all jinja2 --collect-all certifi `
  --add-binary "ffmpeg.exe;." youtube_app.py
```

### macOS `.app` / `.dmg` (Intel)

Потрібні macOS на процесорі Intel (x86_64), Python 3 та ffmpeg у `PATH`:

```bash
chmod +x build.sh
./build.sh
```

Результат: `YouTubeDownloader.dmg`.

## Примітки

- Кодування консолі у Windows: застосунок примусово вмикає UTF-8 для `stdout`/`stderr`, тому кирилиця не викликає збою в консолях із кодуванням `cp1252`.
- Для особистого використання. Переконайтеся, що ваше використання відповідає Умовам користування YouTube та чинному законодавству про авторське право.
