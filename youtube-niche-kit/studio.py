#!/usr/bin/env python3
"""
Work Rewired Studio: the whole video workflow in your browser, on your own computer.

    python studio.py            # opens http://localhost:8765

Edit the script, shot list and thumbnail text, run preview / final / thumbnail builds
with a live progress bar, watch the result, and upload any missing screenshot or clip
straight to the file name it needs. Uses only Python's standard library; the heavy work
is done by voiceover.py, make_video.py and thumbnail.py next to this file.

It only listens on this computer (127.0.0.1), so nothing is reachable from the network.
"""

import argparse
import json
import mimetypes
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import make_video as mv  # noqa: E402
import thumbnail as th  # noqa: E402

PORT = 8765
VOICES = {
    "am_michael": "US male, warm", "am_fenrir": "US male, deeper", "af_heart": "US female, warm",
    "af_bella": "US female, bright", "bm_george": "UK male, documentary", "bm_fable": "UK male, lighter",
    "bf_emma": "UK female",
}
TEXT_FILES = {"script": "script.txt", "shots": "shots.txt", "thumbnail": "thumbnail.txt"}
UPLOAD_DIRS = {"screenshots", "stock", "people", "logos", "charts", "clips", "music", "images"}
UPLOAD_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".mp3", ".wav", ".m4a"}
SAVE_AS = re.compile(r"(?:save one(?: by hand)? as|missing file)\s+(\S+)")
PROGRESS = re.compile(r"(\d+)/(\d+)")
NEW_SCRIPT = "Paste the voiceover here (in your Claude Project, type: VOICE).\n"
NEW_SHOTS = "# Paste the shot list here (in your Claude Project, type: SHOTS).\n1: text: WORK REWIRED | The future of work decoded\n"
NEW_THUMB = "# Paste the thumbnail text here (in your Claude Project, type: THUMB).\ntext: YOUR WORDS\ntrend: down\n"


def find_root():
    """The WorkRewired folder: the one holding 'videos' (tools/.. on the laptop, this folder in the kit)."""
    for candidate in (TOOLS.parent, TOOLS):
        if (candidate / "videos").is_dir():
            return candidate
    return TOOLS.parent


ROOT = find_root()


# ---------------------------------------------------------------- settings & keys

def read_kv(path):
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*([A-Za-z_]+)\s*=\s*(.+?)\s*$", line)
            if m:
                values[m[1].upper()] = m[2]
    return values


def write_kv(path, updates):
    """Set KEY=value lines, keeping any other lines in the file."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Za-z_]+)\s*=", line)
        if m and m[1].upper() in updates:
            lines[i] = f"{m[1].upper()}={updates[m[1].upper()]}"
            done.add(m[1].upper())
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def good_key(value):
    return bool(value) and not re.search(r"paste|\.\.\.|\"|\s", value)


def child_env(root):
    """Environment for the tools: keys.txt + settings.txt, unbuffered UTF-8 output."""
    env = dict(os.environ)
    if not good_key(env.get("PIXABAY_API_KEY", "")):
        env.pop("PIXABAY_API_KEY", None)
    env.update(read_kv(root / "keys.txt"))
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    return env


# ---------------------------------------------------------------- videos on disk

def videos_dir(root):
    return root / "videos"


def video_path(root, name):
    """The folder for a video name, or None if it isn't one of the real video folders."""
    if not name or not re.fullmatch(r"[\w .()-]+", name) or name.strip(".") == "":
        return None
    path = videos_dir(root) / name
    return path if path.is_dir() and path.parent == videos_dir(root) else None


def safe_child(base, rel):
    """base/rel if it stays inside base (no '..', no absolute paths), else None."""
    if not rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel):
        return None
    target = (base / rel).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


def upload_target(folder, rel):
    """Where an uploaded file may go: a known asset folder (or music at the top), allowed type only."""
    rel = rel.replace("\\", "/").strip()
    parts = rel.split("/")
    ext = Path(rel).suffix.lower()
    if ext not in UPLOAD_EXTS or any(p in ("", ".", "..") for p in parts):
        return None
    if len(parts) == 1 and ext not in {".mp3", ".wav", ".m4a"}:
        return None
    if len(parts) > 1 and parts[0] not in UPLOAD_DIRS:
        return None
    return safe_child(folder, rel)


def studio_state(folder):
    path = folder / ".studio.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_studio_state(folder, **values):
    state = studio_state(folder)
    state.update(values)
    (folder / ".studio.json").write_text(json.dumps(state, indent=1), encoding="utf-8")


def missing_items(folder):
    """What the last video build and the last thumbnail build asked for (kept separately, so a
    thumbnails-only run doesn't forget the video's missing clips)."""
    st = studio_state(folder)
    items, seen = [], set()
    for item in st.get("missing_video", st.get("missing", [])) + st.get("missing_thumbs", []):
        if item["path"] not in seen:
            seen.add(item["path"])
            items.append(item)
    return items


def forget_missing(folder, rel):
    st = studio_state(folder)
    updates = {key: [m for m in st.get(key, []) if m["path"] != rel]
               for key in ("missing", "missing_video", "missing_thumbs") if key in st}
    if updates:
        save_studio_state(folder, **updates)


def newer(a, b):
    return a.exists() and (not b.exists() or a.stat().st_mtime > b.stat().st_mtime)


def video_summary(folder):
    def has(name):
        p = folder / name
        return p.exists() and p.stat().st_size > 0
    script = folder / "script.txt"
    words = len(script.read_text(encoding="utf-8", errors="replace").split()) if script.exists() else 0
    return {
        "name": folder.name,
        "script": has("script.txt") and words > 20,
        "words": words,
        "minutes": round(words / 150, 1),
        "shots": has("shots.txt"),
        "thumbnail": has("thumbnail.txt"),
        "voice": has("script.wav") and not newer(script, folder / "script.wav"),
        "preview": has("script_preview.mp4"),
        "final": has("script.mp4"),
        "thumbs": sorted(p.name for p in folder.glob("thumbnail-*.jpg")),
        "missing": sum(1 for m in missing_items(folder) if not (folder / m["path"]).exists()),
        "modified": max((p.stat().st_mtime for p in folder.glob("*") if p.is_file()), default=0),
    }


def list_assets(folder):
    assets = {}
    for sub in sorted(UPLOAD_DIRS | {"screenshots/auto"}):
        d = folder / sub
        if d.is_dir():
            files = sorted(p.name for p in d.iterdir() if p.is_file() and p.suffix.lower() in UPLOAD_EXTS)
            if files:
                assets[sub] = files
    music = sorted(p.name for p in folder.glob("*.mp3"))
    if music:
        assets["music (top folder)"] = music
    return assets


def create_video(root, title):
    """New folder 'NN-title' with starter files. Returns its name."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "video"
    numbers = [int(m[1]) for p in videos_dir(root).iterdir() if (m := re.match(r"(\d+)-", p.name))]
    name = f"{max(numbers, default=0) + 1:02d}-{slug}"
    folder = videos_dir(root) / name
    for sub in ("screenshots", "stock", "charts", "logos"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    (folder / "script.txt").write_text(NEW_SCRIPT, encoding="utf-8")
    (folder / "shots.txt").write_text(NEW_SHOTS, encoding="utf-8")
    (folder / "thumbnail.txt").write_text(NEW_THUMB, encoding="utf-8")
    return name


def check_text(kind, text):
    """Validate a shot list / thumbnail spec the same way the tools will. Returns an error or None."""
    try:
        if kind == "shots":
            shots = mv.parse_shots(text)
            if not shots:
                return "The shot list is empty."
        elif kind == "thumbnail":
            th.parse_spec(text)
    except ValueError as err:
        return str(err)
    return None


def missing_from_output(lines):
    """Pull 'save one as stock/x-0.mp4'-style requests out of a run's output."""
    items = []
    for line in lines:
        m = SAVE_AS.search(line)
        if m:
            path = m[1].rstrip(".,)")
            text = line.strip().lstrip("-").strip()
            if path not in [i["path"] for i in items]:
                items.append({"path": path, "text": text})
    return items


# ---------------------------------------------------------------- background jobs

class Jobs:
    """Runs one build at a time (they use the whole computer) and keeps its output for the page."""

    def __init__(self, root):
        self.root = root
        self.lock = threading.Lock()
        self.job = None
        self.proc = None

    def snapshot(self, since=0):
        with self.lock:
            if not self.job:
                return {"state": "idle"}
            job = dict(self.job)
            lines = job.pop("lines")
            job["lines"] = lines[since:]
            job["next"] = len(lines)
            return job

    def busy(self):
        with self.lock:
            return bool(self.job and self.job["state"] == "running")

    def start(self, kind, video, steps, after=None):
        with self.lock:
            if self.job and self.job["state"] == "running":
                return False
            self.job = {"kind": kind, "video": video, "state": "running", "stage": "", "pct": 0,
                        "lines": [], "started": time.time(), "ended": None, "step": 0, "steps": len(steps)}
        threading.Thread(target=self._run, args=(steps, after), daemon=True).start()
        return True

    def cancel(self):
        with self.lock:
            proc = self.proc
            if self.job and self.job["state"] == "running":
                self.job["state"] = "cancelling"
        if proc and proc.poll() is None:
            kill_tree(proc)

    def _log(self, text):
        with self.lock:
            self.job["lines"].append(text)
            del self.job["lines"][:-4000]  # keep the page light
            m = PROGRESS.search(text)
            if m and int(m[2]) > 0:
                self.job["pct"] = min(100, round(100 * int(m[1]) / int(m[2])))

    def _run(self, steps, after):
        state = "done"
        for i, (label, cmd) in enumerate(steps):
            with self.lock:
                if self.job["state"] == "cancelling":
                    state = "cancelled"
                    break
                self.job.update(stage=label, pct=0, step=i + 1)
            self._log(f"=== {label} ===")
            try:
                proc = spawn(cmd, self.root)
            except OSError as err:
                self._log(f"Couldn't start: {err}")
                state = "failed"
                break
            with self.lock:
                self.proc = proc
            buf = b""
            while True:
                chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                *parts, buf = re.split(rb"[\r\n]", buf)
                for part in parts:
                    if part.strip():
                        self._log(part.decode("utf-8", "replace"))
            if buf.strip():
                self._log(buf.decode("utf-8", "replace"))
            code = proc.wait()
            with self.lock:
                self.proc = None
                cancelled = self.job["state"] == "cancelling"
            if cancelled:
                state = "cancelled"
                break
            if code != 0:
                self._log(f"(stopped: exit code {code})")
                state = "failed"
                break
        with self.lock:
            lines = list(self.job["lines"])
        if after:
            try:
                after(state, lines)
            except Exception as err:  # never lose the job result over bookkeeping
                self._log(f"(note: {err})")
        with self.lock:
            self.job.update(state=state, ended=time.time(), pct=100 if state == "done" else self.job["pct"])


def spawn(cmd, root):
    kwargs = {"cwd": str(root), "env": child_env(root), "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
              "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def kill_tree(proc):
    """Stop a build and everything it started (ffmpeg, the screenshot browser...)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def build_steps(root, folder, kind, voice):
    """The same steps MAKE-VIDEO runs: voiceover if the script changed, video, thumbnails."""
    py = sys.executable
    steps = []
    script, wav = folder / "script.txt", folder / "script.wav"
    if kind in ("preview", "final"):
        if newer(script, wav) or not wav.exists():
            steps.append((f"Voiceover ({voice})", [py, str(TOOLS / "voiceover.py"), str(script), "--voice", voice]))
        args = [py, str(TOOLS / "make_video.py"), str(wav), str(folder / "shots.txt")]
        if kind == "preview":
            args.append("--preview")
        music = sorted(folder.glob("*.mp3"))
        if music:
            args += ["--music", str(music[0])]
        steps.append(("Preview video" if kind == "preview" else "Final 1080p video", args))
    if kind == "thumbs" or (folder / "thumbnail.txt").exists():
        steps.append(("Thumbnails", [py, str(TOOLS / "thumbnail.py"), str(folder / "thumbnail.txt")]))
    return steps


# ---------------------------------------------------------------- web server

class Studio(BaseHTTPRequestHandler):
    server_version = "WorkRewiredStudio/1.0"
    root = ROOT
    jobs = None

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # --- helpers
    def _allowed_host(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("localhost", "127.0.0.1", "[::1]")

    def _send(self, status, body=b"", ctype="application/json", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status=HTTPStatus.OK):
        self._send(status, json.dumps(data).encode("utf-8"))

    def _error(self, message, status=HTTPStatus.BAD_REQUEST):
        self._json({"error": message}, status)

    def _body(self, limit=5_000_000):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise ValueError("too large")
        return self.rfile.read(length)

    def _route(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
        return parts, urllib.parse.parse_qs(parsed.query)

    def _guard(self, write=False):
        """Only this computer, and (for changes) only our own page - not other websites."""
        if not self._allowed_host():
            self._error("Studio only answers on localhost", HTTPStatus.FORBIDDEN)
            return False
        if write and self.headers.get("X-Studio") != "1":
            self._error("missing X-Studio header", HTTPStatus.FORBIDDEN)
            return False
        return True

    # --- GET
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._guard():
            return
        parts, query = self._route()
        if not parts:
            page = (TOOLS / "studio.html").read_bytes()
            return self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
        if parts == ["api", "state"]:
            return self._json(self.state())
        if parts == ["api", "job"]:
            since = int((query.get("since") or ["0"])[0] or 0)
            return self._json(self.jobs.snapshot(since))
        if len(parts) == 3 and parts[:2] == ["api", "videos"]:
            folder = video_path(self.root, parts[2])
            return self._json(self.video(folder)) if folder else self._error("no such video", HTTPStatus.NOT_FOUND)
        if len(parts) >= 3 and parts[0] == "media":
            folder = video_path(self.root, parts[1])
            target = safe_child(folder, "/".join(parts[2:])) if folder else None
            return self._file(target)
        if len(parts) == 2 and parts[0] == "samples":
            return self._file(safe_child(self.root / "voice_samples", parts[1]))
        self._error("not found", HTTPStatus.NOT_FOUND)

    def _file(self, path):
        """Serve a file, with byte ranges so videos can be scrubbed in the browser."""
        if not path or not path.is_file():
            return self._error("not found", HTTPStatus.NOT_FOUND)
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        status = HTTPStatus.OK
        if rng and size:
            if rng[1]:
                start = int(rng[1])
                end = int(rng[2]) if rng[2] else size - 1
            else:  # last N bytes
                start = max(0, size - int(rng[2] or 0))
            end = min(end, size - 1)
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            status = HTTPStatus.PARTIAL_CONTENT
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser stopped watching

    # --- POST / PUT
    def do_POST(self):
        if not self._guard(write=True):
            return
        parts, _ = self._route()
        try:
            data = json.loads(self._body() or b"{}")
        except ValueError:
            return self._error("bad request body")
        if parts == ["api", "videos"]:
            title = str(data.get("title", "")).strip()
            if not title:
                return self._error("Give the video a name.")
            return self._json({"name": create_video(self.root, title)})
        if parts == ["api", "job", "cancel"]:
            self.jobs.cancel()
            return self._json({"ok": True})
        if parts == ["api", "settings"]:
            return self._settings(data)
        if parts == ["api", "update"]:
            return self._update()
        if len(parts) == 4 and parts[:2] == ["api", "videos"] and parts[3] == "run":
            folder = video_path(self.root, parts[2])
            if not folder:
                return self._error("no such video", HTTPStatus.NOT_FOUND)
            return self._run(folder, str(data.get("kind", "")))
        self._error("not found", HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        if not self._guard(write=True):
            return
        parts, query = self._route()
        if len(parts) < 4 or parts[:2] != ["api", "videos"]:
            return self._error("not found", HTTPStatus.NOT_FOUND)
        folder = video_path(self.root, parts[2])
        if not folder:
            return self._error("no such video", HTTPStatus.NOT_FOUND)
        if len(parts) == 5 and parts[3] == "text" and parts[4] in TEXT_FILES:
            try:
                text = self._body().decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return self._error("That text couldn't be read.")
            text = text.replace("\r\n", "\n")
            (folder / TEXT_FILES[parts[4]]).write_text(text, encoding="utf-8")
            return self._json({"ok": True, "problem": check_text(parts[4], text)})
        if len(parts) == 4 and parts[3] == "upload":
            target = upload_target(folder, (query.get("path") or [""])[0])
            if not target:
                return self._error("Files can go into screenshots, stock, people, logos, charts, clips or "
                                   "images (pictures, clips) - or music (.mp3) in the top folder.")
            return self._upload(folder, target)
        self._error("not found", HTTPStatus.NOT_FOUND)

    def _upload(self, folder, target):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 4_000_000_000:
            return self._error("empty or too large")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        left = length
        with open(tmp, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            tmp.unlink(missing_ok=True)
            return self._error("upload was cut off - try again")
        os.replace(tmp, target)
        rel = target.relative_to(folder.resolve()).as_posix()
        forget_missing(folder, rel)
        return self._json({"ok": True, "path": rel})

    def _run(self, folder, kind):
        if kind not in ("preview", "final", "thumbs"):
            return self._error("unknown build")
        if kind == "thumbs" and not (folder / "thumbnail.txt").exists():
            return self._error("Add a thumbnail.txt first (in your Claude Project, type: THUMB).")
        if kind != "thumbs":
            for name in ("script.txt", "shots.txt"):
                if not (folder / name).exists():
                    return self._error(f"This video has no {name} yet.")
            problem = check_text("shots", (folder / "shots.txt").read_text(encoding="utf-8"))
            if problem:
                return self._error(f"Fix the shot list first: {problem}")
        voice = read_kv(self.root / "settings.txt").get("VOICE", "am_michael")
        steps = build_steps(self.root, folder, kind, voice)

        def after(state, lines):
            if state != "done":
                return
            split = next((i for i, line in enumerate(lines) if line.startswith("=== Thumbnails")), len(lines))
            updates = {"missing_thumbs": missing_from_output(lines[split:]), "last": kind, "at": time.time()}
            if kind != "thumbs":
                updates["missing_video"] = missing_from_output(lines[:split])
            save_studio_state(folder, **updates)
        if not self.jobs.start(kind, folder.name, steps, after):
            return self._error("Something is already being built - wait for it or cancel it.", HTTPStatus.CONFLICT)
        return self._json({"ok": True})

    def _settings(self, data):
        if "voice" in data:
            if data["voice"] not in VOICES:
                return self._error("unknown voice")
            write_kv(self.root / "settings.txt", {"VOICE": data["voice"]})
        if data.get("pixabay_key") is not None:
            key = str(data["pixabay_key"]).strip().strip('"')
            if key and not good_key(key):
                return self._error("That doesn't look like a Pixabay key.")
            write_kv(self.root / "keys.txt", {"PIXABAY_API_KEY": key})
        return self._json({"ok": True})

    def _update(self):
        updater = TOOLS / "update.ps1"
        if os.name != "nt" or not updater.exists():
            return self._error("Updates run on the Windows app (UPDATE.bat).")
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater)]
        if not self.jobs.start("update", "", [("Checking for updates", cmd)]):
            return self._error("Something is already running.", HTTPStatus.CONFLICT)
        return self._json({"ok": True})

    # --- data for the page
    def state(self):
        vids = []
        if videos_dir(self.root).is_dir():
            for folder in sorted(p for p in videos_dir(self.root).iterdir() if p.is_dir()):
                vids.append(video_summary(folder))
        settings = read_kv(self.root / "settings.txt")
        key = read_kv(self.root / "keys.txt").get("PIXABAY_API_KEY", "")
        samples = sorted(p.stem for p in (self.root / "voice_samples").glob("*.wav"))
        return {
            "videos": vids, "voice": settings.get("VOICE", "am_michael"),
            "voices": [{"id": k, "label": v, "sample": k in samples} for k, v in VOICES.items()],
            "pixabay": f"…{key[-4:]}" if good_key(key) else "",
            "ffmpeg": bool(shutil.which("ffmpeg")), "windows": os.name == "nt",
            "job": self.jobs.snapshot(10**9),
        }

    def video(self, folder):
        texts = {k: ((folder / f).read_text(encoding="utf-8", errors="replace") if (folder / f).exists() else "")
                 for k, f in TEXT_FILES.items()}
        credits = folder / "credits.txt"
        return {
            **video_summary(folder), "texts": texts,
            "problems": {k: check_text(k, texts[k]) for k in ("shots", "thumbnail") if texts[k]},
            "missing": [dict(m, exists=(folder / m["path"]).exists()) for m in missing_items(folder)],
            "credits": credits.read_text(encoding="utf-8") if credits.exists() else "",
            "srt": (folder / "script.srt").exists(),
            "assets": list_assets(folder),
            "versions": {n: int((folder / n).stat().st_mtime) for n in
                         ("script.mp4", "script_preview.mp4", *[p.name for p in folder.glob("thumbnail-*.jpg")])
                         if (folder / n).exists()},
        }


def already_running(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def make_server(root=ROOT, port=PORT):
    handler = type("Handler", (Studio,), {"root": root, "jobs": Jobs(root)})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main(argv=None):
    p = argparse.ArgumentParser(description="Work Rewired Studio (opens in your browser)")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv)
    url = f"http://localhost:{args.port}"
    if already_running(args.port):
        print(f"Studio is already running - opening {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    server = make_server(ROOT, args.port)
    print("=== Work Rewired Studio ===")
    print(f"Open {url} in your browser (it should open by itself).")
    print("Leave this window open while you work. Close it to stop Studio.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
