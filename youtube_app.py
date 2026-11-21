import os
import re
import uuid
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, request, jsonify
import yt_dlp
import sys
import socket
import subprocess
import time
import json
import hashlib
import zipfile
import shutil
import ssl
import importlib
import importlib.machinery
import urllib.request

# ---------- автоматичне оновлення yt-dlp ----------
# Нові версії завантажуються з PyPI до папки користувача та використовуються
# замість версії, вбудованої у застосунок.
if sys.platform == "darwin":
    _APPDATA = Path.home() / "Library" / "Application Support"
elif sys.platform == "win32":
    _APPDATA = Path(os.environ.get("APPDATA", str(Path.home())))
else:
    _APPDATA = Path.home() / ".local" / "share"

UPDATE_ROOT = _APPDATA / "YouTubeDownloader" / "yt_update"
UPDATE_SITE = {"path": None}
_update_lock = threading.Lock()
_last_update_try = {"t": 0.0}

OUTDATED_HINTS = (
    "page needs to be reloaded", "sign in to confirm", "http error 403",
    "unable to extract", "requested format is not available", "nsig",
    "sabr", "player response", "challenge", "unable to download video data",
    "n function",
)


def _vtuple(v):
    out = []
    for part in str(v).split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


class _UpdatedFinder:
    # yt_dlp і yt_dlp_ejs завантажуємо з папки оновлення раніше, ніж із застосунку
    def find_spec(self, name, path=None, target=None):
        site = UPDATE_SITE["path"]
        if site is None or name.partition(".")[0] not in ("yt_dlp", "yt_dlp_ejs"):
            return None
        return importlib.machinery.PathFinder.find_spec(name, path or [site])


sys.meta_path.insert(0, _UpdatedFinder())


def _reload_ytdlp():
    global yt_dlp
    for m in [m for m in sys.modules
              if m.partition(".")[0] in ("yt_dlp", "yt_dlp_ejs")]:
        del sys.modules[m]
    importlib.invalidate_caches()
    import yt_dlp as _new
    yt_dlp = _new


def _installed_version():
    try:
        return importlib.import_module("yt_dlp.version").__version__
    except Exception:
        return "0"


def _newest_update_dir():
    best = None
    if UPDATE_ROOT.is_dir():
        for d in UPDATE_ROOT.iterdir():
            if d.is_dir() and d.name.startswith("site-") and (d / "yt_dlp").is_dir():
                v = d.name[5:]
                if best is None or _vtuple(v) > _vtuple(best[0]):
                    best = (v, d)
    return best


def _http_get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "YouTubeDownloader"})
    contexts = []
    try:
        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    contexts.append(ssl.create_default_context())  # системні сертифікати
    last = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read()
        except Exception as e:
            last = e
    raise last


def _fetch_wheel(project, dest):
    meta = json.loads(_http_get(f"https://pypi.org/pypi/{project}/json"))
    for f in meta["urls"]:
        if f["packagetype"] == "bdist_wheel" and f["filename"].endswith("none-any.whl"):
            data = _http_get(f["url"], timeout=300)
            if hashlib.sha256(data).hexdigest() != f["digests"]["sha256"]:
                raise RuntimeError("Контрольна сума не збігається")
            tmp = dest / "_wheel.zip"
            tmp.write_bytes(data)
            with zipfile.ZipFile(tmp) as z:
                z.extractall(dest)
            tmp.unlink()
            return meta["info"]["version"]
    raise RuntimeError(f"Не знайдено wheel для {project}")


def try_update_ytdlp():
    """Завантажує актуальну версію yt-dlp. Повертає True, якщо встановлено новішу версію."""
    with _update_lock:
        now = time.time()
        if now - _last_update_try["t"] < 600:
            return False
        _last_update_try["t"] = now
        try:
            meta = json.loads(_http_get("https://pypi.org/pypi/yt-dlp/json"))
            latest = meta["info"]["version"]
            if _vtuple(latest) <= _vtuple(_installed_version()):
                return False

            UPDATE_ROOT.mkdir(parents=True, exist_ok=True)
            tmp = UPDATE_ROOT / f"tmp-{int(now)}"
            tmp.mkdir()
            try:
                _fetch_wheel("yt-dlp", tmp)
                try:
                    _fetch_wheel("yt-dlp-ejs", tmp)
                except Exception:
                    pass
                final = UPDATE_ROOT / f"site-{latest}"
                if final.exists():
                    shutil.rmtree(final)
                tmp.rename(final)
            except Exception:
                shutil.rmtree(tmp, ignore_errors=True)
                raise

            UPDATE_SITE["path"] = str(final)
            _reload_ytdlp()
            for d in UPDATE_ROOT.iterdir():
                if (d.is_dir() and d != final
                        and d.name.startswith(("site-", "tmp-"))):
                    shutil.rmtree(d, ignore_errors=True)
            return True
        except Exception:
            return False


def looks_outdated(err):
    t = str(err).lower()
    return any(h in t for h in OUTDATED_HINTS)


def with_auto_update(fn):
    try:
        return fn()
    except Exception as e:
        if not looks_outdated(e):
            raise
        if try_update_ytdlp():
            return fn()
        raise RuntimeError(
            str(e) + "\n\nПідказка: YouTube міг змінити захист, а нової "
            "версії yt-dlp поки немає. Спробуй пізніше."
        ) from e


# під час запуску використовуємо оновлення, якщо воно новіше за вбудовану версію
_best = _newest_update_dir()
if _best and _vtuple(_best[0]) > _vtuple(_installed_version()):
    UPDATE_SITE["path"] = str(_best[1])
    try:
        _reload_ytdlp()
    except Exception:
        UPDATE_SITE["path"] = None
        _reload_ytdlp()

# Папка, у якій розташований exe-файл (або скрипт). Сюди можна додати ffmpeg.exe та deno.exe:
# застосунок знайде їх автоматично.
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    # у зібраному застосунку ffmpeg і deno розташовані поруч із ресурсами
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    EXTRA_DIRS = [BASE_DIR, Path(sys.executable).parent]
else:
    BASE_DIR = Path(__file__).resolve().parent
    EXTRA_DIRS = [BASE_DIR]
os.environ["PATH"] = (
    os.pathsep.join(str(d) for d in EXTRA_DIRS)
    + os.pathsep + os.environ.get("PATH", "")
)
# у застосунку без консолі потоки stdout/stderr можуть бути відсутні
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
# Windows-консоль за замовчуванням cp1252 і не вміє кирилицю: примусово UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = Flask(__name__)

DOWNLOAD_DIR = Path.home() / "Downloads"
PORT = 5000

jobs = {}
jobs_lock = threading.Lock()


def valid_url(url):
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        return p.scheme in ("http", "https") and (
            host == "youtu.be"
            or host == "youtube.com"
            or host.endswith(".youtube.com")
        )
    except Exception:
        return False


def build_format(quality):
    if quality == "audio":
        return "bestaudio/best"
    if quality == "best":
        # H.264 + AAC відтворюється у QuickTime; якщо такого формату немає, використовуємо доступний
        return ("bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]"
                "/bestvideo*+bestaudio/best")
    h = int(quality)
    if h > 1080:
        return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"
    return (f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={h}]+bestaudio/best[height<={h}]")


@app.route("/")
def index():
    return PAGE


@app.route("/api/info", methods=["POST"])
def api_info():
    url = (request.json or {}).get("url", "").strip()
    if not valid_url(url):
        return jsonify(error="Некоректне посилання на YouTube"), 400

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    def fetch():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = with_auto_update(fetch)
    except Exception as e:
        return jsonify(error=str(e)), 400

    heights = sorted(
        {
            f["height"]
            for f in info.get("formats", [])
            if f.get("height") and f.get("vcodec") not in (None, "none")
        },
        reverse=True,
    )

    return jsonify(
        id=info.get("id"),
        title=info.get("title"),
        channel=info.get("uploader"),
        duration=info.get("duration"),
        thumbnail=info.get("thumbnail"),
        heights=heights,
    )


def run_job(job_id, url, quality, folder):
    def hook(d):
        with jobs_lock:
            job = jobs[job_id]
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes", 0)
                job["percent"] = done / total * 100 if total else 0
                speed = d.get("speed")
                job["speed"] = f"{speed / 1024 / 1024:.2f} MB/s" if speed else "—"
                job["eta"] = d.get("eta")
                vcodec = (d.get("info_dict") or {}).get("vcodec")
                job["stage"] = "Аудіо" if vcodec == "none" else "Відео"
                job["state"] = "downloading"
            elif d["status"] == "finished":
                job["state"] = "processing"

    opts = {
        "format": build_format(quality),
        "format_sort": ["res", "ext:mp4:m4a"],
        "outtmpl": str(Path(folder) / "%(title).180B.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 16,
        "http_chunk_size": 10 * 1024 * 1024,
        "socket_timeout": 30,
    }

    if quality == "audio":
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]

    def do_download():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            rd = info.get("requested_downloads") or [{}]
            return rd[0].get("filepath") or ydl.prepare_filename(info)

    try:
        Path(folder).mkdir(parents=True, exist_ok=True)
        path = with_auto_update(do_download)
        with jobs_lock:
            jobs[job_id].update(state="done", percent=100, path=str(path))
    except Exception as e:
        with jobs_lock:
            jobs[job_id].update(state="error", error=str(e))


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.json or {}
    url = data.get("url", "").strip()
    quality = str(data.get("quality", "best"))
    folder = (data.get("folder") or "").strip() or str(DOWNLOAD_DIR)

    if not valid_url(url):
        return jsonify(error="Некоректне посилання на YouTube"), 400
    if quality not in ("best", "audio") and not quality.isdigit():
        return jsonify(error="Некоректна якість"), 400

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"state": "starting", "percent": 0, "speed": "—",
                        "eta": None, "stage": "", "path": "", "error": ""}

    threading.Thread(target=run_job, args=(job_id, url, quality, folder),
                     daemon=True).start()
    return jsonify(job=job_id)


@app.route("/api/status/<job_id>")
def api_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        return jsonify(job) if job else (jsonify(error="Не знайдено"), 404)


pages = {}  # id вкладки -> час останнього сигналу
pages_lock = threading.Lock()
seen_any_page = {"v": False}


def _page_id():
    try:
        return str(json.loads(request.get_data(as_text=True) or "{}").get("id") or "?")
    except Exception:
        return "?"


@app.route("/api/ping", methods=["POST"])
def api_ping():
    with pages_lock:
        pages[_page_id()] = time.time()
        seen_any_page["v"] = True
    return jsonify(ok=True)


@app.route("/api/bye", methods=["POST"])
def api_bye():
    # вкладку закрито (sendBeacon): одразу забуваємо її
    with pages_lock:
        pages.pop(_page_id(), None)
    return ("", 204)


def idle_watcher():
    # режим застосунку: виходимо через кілька секунд після закриття останньої вкладки
    empty_since = None
    while True:
        time.sleep(1)
        now = time.time()
        with pages_lock:
            # вкладки без сигналів 2 хвилини (браузер вбито тощо) вважаємо закритими
            for pid in [p for p, t in pages.items() if now - t > 120]:
                pages.pop(pid, None)
            has_pages = bool(pages)
        if has_pages or not seen_any_page["v"]:
            empty_since = None
            continue
        with jobs_lock:
            busy = any(
                j["state"] in ("starting", "downloading", "processing")
                for j in jobs.values()
            )
        if busy:
            empty_since = None
            continue
        if empty_since is None:
            empty_since = now
        elif now - empty_since >= 5:
            os._exit(0)


@app.route("/api/default-folder")
def api_default_folder():
    return jsonify(folder=str(DOWNLOAD_DIR))


def choose_folder_dialog(initial):
    # у macOS tkinter не можна запускати поза головним потоком, тому використовуємо osascript
    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "Папка для збереження"'
        if initial and Path(initial).is_dir():
            safe = initial.replace("\\", "\\\\").replace('"', '\\"')
            script += f' default location POSIX file "{safe}"'
        script += ")"
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(
            initialdir=initial, title="Папка для збереження"
        )
    finally:
        root.destroy()


def open_in_file_manager(folder):
    try:
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass


@app.route("/api/choose-folder", methods=["POST"])
def api_choose_folder():
    initial = (request.json or {}).get("initial") or str(DOWNLOAD_DIR)
    folder = choose_folder_dialog(initial)
    return jsonify(folder=os.path.normpath(folder) if folder else "")


@app.route("/api/open-folder", methods=["POST"])
def api_open_folder():
    job_id = (request.json or {}).get("job")
    with jobs_lock:
        job = jobs.get(job_id)
        path = job["path"] if job else ""
    if path:
        open_in_file_manager(str(Path(path).parent))
    return jsonify(ok=True)


PAGE = """<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>YouTube Downloader</title>
<link rel="icon" type="image/png" href="data:image/png;base64,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">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #0f1115; color: #e8e8ea;
         font-family: "Segoe UI", system-ui, sans-serif; }
  .wrap { max-width: 760px; margin: 0 auto; padding: 40px 20px; }
  h1 { margin: 0 0 6px; font-size: 30px; }
  .sub { color: #8b8f98; margin-bottom: 24px; }
  .row { display: flex; gap: 10px; }
  input[type=text] { flex: 1; padding: 14px 16px; font-size: 16px;
         background: #1a1d24; color: #fff; border: 1px solid #2a2e38;
         border-radius: 10px; outline: none; }
  input[type=text]:focus { border-color: #ff3b3b; }
  button { padding: 14px 22px; font-size: 15px; font-weight: 600;
           background: #ff3b3b; color: #fff; border: 0; border-radius: 10px;
           cursor: pointer; }
  button:hover { background: #ff5555; }
  button:disabled { background: #444; cursor: default; }
  button.ghost { background: #232733; }
  button.ghost:hover { background: #2d3242; }
  .card { margin-top: 24px; background: #171a21; border: 1px solid #252a35;
          border-radius: 14px; overflow: hidden; display: none; }
  .player { position: relative; padding-top: 56.25%; background: #000; }
  .player iframe, .player img { position: absolute; inset: 0; width: 100%;
          height: 100%; border: 0; object-fit: cover; }
  .meta { padding: 18px 20px 6px; }
  .title { font-size: 18px; font-weight: 600; margin-bottom: 4px; }
  .chan { color: #8b8f98; font-size: 14px; }
  .actions { padding: 14px 20px 20px; display: flex; gap: 10px; }
  select { flex: 1; padding: 13px 14px; font-size: 15px; background: #1a1d24;
           color: #fff; border: 1px solid #2a2e38; border-radius: 10px; }
  .folder { padding: 0 20px 14px; display: flex; gap: 10px;
            align-items: center; }
  .folder .path { flex: 1; color: #b5b8c0; font-size: 14px;
                  word-break: break-all; }
  .note { margin: 14px 20px 0; padding: 10px 14px; font-size: 13px;
          line-height: 1.45; color: #b5b8c0; background: #1d212b;
          border-left: 3px solid #ff3b3b; border-radius: 6px; }
  .bar { height: 10px; background: #232733; border-radius: 6px;
         overflow: hidden; margin: 0 20px; display: none; }
  .bar div { height: 100%; width: 0; background: #ff3b3b;
             transition: width .3s; }
  .status { padding: 10px 20px 20px; color: #b5b8c0; font-size: 14px;
            min-height: 20px; word-break: break-word; }
  .err { color: #ff7a7a; }
  .ok { color: #6be08a; }
</style>
</head>
<body>
<div class="wrap">
  <h1>YouTube Downloader</h1>
  <div class="sub">Встав посилання, обери якість і завантаж відео. Усе працює локально.</div>

  <div class="row">
    <input id="url" type="text" placeholder="https://www.youtube.com/watch?v=..." autofocus>
    <button id="go">Знайти</button>
  </div>
  <div id="msg" class="status err"></div>

  <div id="card" class="card">
    <div id="player" class="player"></div>
    <div class="note">
      Якщо у програвачі написано «Відео недоступне» або він не відображається, це
      нормально: автор заборонив показ на інших сайтах. На завантаження це не
      впливає. Відео завантажиться як зазвичай, а якщо потрібна лише музика, обери
      у списку «Лише аудіо (MP3)».
    </div>
    <div class="meta">
      <div id="title" class="title"></div>
      <div id="chan" class="chan"></div>
    </div>
    <div class="folder">
      <span class="path" id="folderPath"></span>
      <button id="chooseFolder" class="ghost">Обрати папку</button>
    </div>
    <div class="actions">
      <select id="quality"></select>
      <button id="dl">Завантажити</button>
    </div>
    <div id="bar" class="bar"><div id="fill"></div></div>
    <div id="status" class="status"></div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let timer = null;
let folder = "";

const pageId = Math.random().toString(36).slice(2) + Date.now().toString(36);
const sendPing = () => fetch("/api/ping", {
  method: "POST", body: JSON.stringify({id: pageId}), keepalive: true
}).catch(() => {});
setInterval(sendPing, 5000);
sendPing();
window.addEventListener("pagehide", () => {
  try { navigator.sendBeacon("/api/bye", JSON.stringify({id: pageId})); } catch (e) {}
});

fetch("/api/default-folder").then(r => r.json()).then(d => {
  folder = d.folder;
  $("folderPath").textContent = "Зберігати в: " + folder;
});

$("chooseFolder").onclick = async () => {
  try {
    const d = await post("/api/choose-folder", {initial: folder});
    if (d.folder) {
      folder = d.folder;
      $("folderPath").textContent = "Зберігати в: " + folder;
    }
  } catch (e) { /* діалог закрито або сталася помилка */ }
};

$("url").addEventListener("keydown", e => { if (e.key === "Enter") find(); });
$("go").onclick = find;
$("dl").onclick = startDownload;

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {})
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "Помилка");
  return data;
}

function fmtDur(s) {
  if (!s) return "";
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60;
  const pad = n => String(n).padStart(2, "0");
  return h ? h + ":" + pad(m) + ":" + pad(sec) : m + ":" + pad(sec);
}

async function find() {
  const url = $("url").value.trim();
  $("msg").textContent = "";
  $("card").style.display = "none";
  if (!url) { $("msg").textContent = "Встав посилання на відео"; return; }

  $("go").disabled = true;
  $("go").textContent = "Шукаю...";
  try {
    const info = await post("/api/info", {url});

    const player = $("player");
    player.innerHTML = "";
    if (/^[\\w-]{11}$/.test(info.id || "")) {
      const f = document.createElement("iframe");
      f.src = "https://www.youtube-nocookie.com/embed/" + info.id;
      f.allow = "accelerometer; autoplay; encrypted-media; picture-in-picture";
      f.allowFullscreen = true;
      f.referrerPolicy = "strict-origin-when-cross-origin";
      player.appendChild(f);
    } else if (info.thumbnail) {
      const img = document.createElement("img");
      img.src = info.thumbnail;
      player.appendChild(img);
    }

    $("title").textContent = info.title || "";
    const dur = fmtDur(info.duration);
    $("chan").textContent = (info.channel || "") + (dur ? "  •  " + dur : "");

    const sel = $("quality");
    sel.innerHTML = "";
    const add = (v, t) => {
      const o = document.createElement("option");
      o.value = v; o.textContent = t; sel.appendChild(o);
    };
    add("best", "Найкраща якість (MP4)");
    (info.heights || []).forEach(h => add(h, h + "p (MP4)"));
    add("audio", "Лише аудіо (MP3)");

    $("bar").style.display = "none";
    $("status").textContent = "";
    $("status").className = "status";
    $("dl").disabled = false;
    $("card").style.display = "block";
  } catch (e) {
    $("msg").textContent = e.message;
  } finally {
    $("go").disabled = false;
    $("go").textContent = "Знайти";
  }
}

async function startDownload() {
  const url = $("url").value.trim();
  $("dl").disabled = true;
  $("bar").style.display = "block";
  $("fill").style.width = "0%";
  $("status").className = "status";
  $("status").textContent = "Підготовка до завантаження...";
  try {
    const {job} = await post("/api/download", {url, quality: $("quality").value, folder});
    clearInterval(timer);
    timer = setInterval(() => poll(job), 500);
  } catch (e) {
    $("status").className = "status err";
    $("status").textContent = e.message;
    $("dl").disabled = false;
  }
}

async function poll(job) {
  try {
    const r = await fetch("/api/status/" + job);
    const s = await r.json();
    $("fill").style.width = (s.percent || 0) + "%";

    if (s.state === "downloading") {
      const eta = s.eta != null ? s.eta + " с." : "—";
      $("status").textContent = s.stage + ": " + s.percent.toFixed(1) + "% | " +
                                s.speed + " | залишилось: " + eta;
    } else if (s.state === "processing") {
      $("status").textContent = "Об’єднання відео й аудіо...";
    } else if (s.state === "done") {
      clearInterval(timer);
      $("fill").style.width = "100%";
      $("status").className = "status ok";
      $("status").innerHTML = "";
      const t = document.createElement("div");
      t.textContent = "Готово! Збережено: " + s.path;
      const b = document.createElement("button");
      b.className = "ghost";
      b.style.marginTop = "10px";
      b.textContent = "Відкрити папку";
      b.onclick = () => post("/api/open-folder", {job});
      $("status").append(t, b);
      $("dl").disabled = false;
    } else if (s.state === "error") {
      clearInterval(timer);
      $("status").className = "status err";
      $("status").textContent = "Помилка: " + s.error;
      $("dl").disabled = false;
    }
  } catch (e) { /* ігноруємо тимчасовий збій опитування */ }
}
</script>
</body>
</html>
"""


def open_ui(url):
    # відкриваємо інтерфейс у браузері за замовчуванням (звичайна вкладка)
    webbrowser.open(url)


def offer_desktop_shortcut():
    """Windows, перший запуск exe: один раз питаємо, чи створити ярлик."""
    if sys.platform != "win32" or not FROZEN:
        return
    marker = _APPDATA / "YouTubeDownloader" / "shortcut_asked"
    try:
        if marker.exists():
            return
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1")

        import ctypes
        MB_YESNO, MB_ICONQUESTION, IDYES = 0x4, 0x20, 6
        answer = ctypes.windll.user32.MessageBoxW(
            0, "Створити ярлик на робочому столі?", "YouTube Downloader",
            MB_YESNO | MB_ICONQUESTION)
        if answer != IDYES:
            return

        exe = sys.executable.replace("'", "''")
        folder = str(Path(sys.executable).parent).replace("'", "''")
        ps = (
            "$d=[Environment]::GetFolderPath('Desktop');"
            "$s=(New-Object -ComObject WScript.Shell)"
            ".CreateShortcut(\"$d\\YouTube Downloader.lnk\");"
            f"$s.TargetPath='{exe}';$s.WorkingDirectory='{folder}';"
            f"$s.IconLocation='{exe},0';$s.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=0x08000000,  # без вікна консолі
        )
    except Exception:
        pass


if __name__ == "__main__":
    # якщо застосунок уже запущено, просто відкриваємо браузер
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", PORT)) == 0:
            open_ui(f"http://127.0.0.1:{PORT}")
            sys.exit(0)

    print(f"YouTube Downloader запущено: http://127.0.0.1:{PORT}")
    print("Не закривай це вікно, поки користуєшся програмою. Після закриття сервер зупиниться.")
    threading.Timer(1.0, lambda: open_ui(f"http://127.0.0.1:{PORT}")).start()
    threading.Thread(target=offer_desktop_shortcut, daemon=True).start()
    if "--app" in sys.argv or FROZEN:
        threading.Thread(target=idle_watcher, daemon=True).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
