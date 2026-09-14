#!/usr/bin/env python3
"""
YouTube Downloader - local server
Pure standard library (no Flask/etc needed). Wraps yt-dlp and serves a
simple web UI on localhost so you never have to touch the terminal.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8642
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Default save location: Downloads/YT (falls back to a local "downloads"
# folder next to this script if that path doesn't exist for some reason).
HOME = os.path.expanduser("~")
DEFAULT_OUTPUT_DIR = os.path.join(HOME, "Downloads", "YT")
if not os.path.isdir(os.path.dirname(DEFAULT_OUTPUT_DIR)):
    DEFAULT_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "downloads")
os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

# YouTube now requires a JavaScript runtime to decrypt player responses, and
# blocks anonymous requests with "Sign in to confirm you're not a bot". We
# detect a usable runtime (yt-dlp only enables deno by default) and pass the
# user's browser cookies to get past the bot check.
# Same order yt-dlp itself prioritises them (see `yt-dlp --js-runtimes`).
JS_RUNTIMES = ("deno", "node", "quickjs", "bun")


def detect_js_runtime():
    for name in JS_RUNTIMES:
        if shutil.which(name):
            return name
    return None


# Browsers yt-dlp can pull cookies from, in the order we try them. A browser
# that's installed but was never used for YouTube just yields no useful
# cookies, so the download still falls back to an anonymous attempt.
COOKIE_BROWSERS = ("chrome", "brave", "edge", "firefox", "safari")
BROWSER_APP_PATHS = {
    "chrome": "Google Chrome.app",
    "brave": "Brave Browser.app",
    "edge": "Microsoft Edge.app",
    "firefox": "Firefox.app",
    "safari": "Safari.app",
}


def detect_cookie_browser():
    for name in COOKIE_BROWSERS:
        app = BROWSER_APP_PATHS[name]
        for base in ("/Applications", os.path.join(HOME, "Applications")):
            if os.path.exists(os.path.join(base, app)):
                return name
    return None


JS_RUNTIME = detect_js_runtime()
COOKIE_BROWSER = detect_cookie_browser()

# Reading cookies straight from Chrome means asking macOS for the browser's
# Keychain encryption key, which pops a password prompt -- twice per download,
# since yt-dlp fetches the video and audio streams as separate passes. So we
# export once to a plain cookie file and reuse it. Only a re-export touches
# the Keychain again, and that only happens when the cookies stop working
# (signing out of YouTube or changing your Google password invalidates them;
# the auth cookies themselves carry far-future expiry dates).
COOKIE_FILE = os.path.join(SCRIPT_DIR, ".cookies.txt")


def export_cookies():
    """Export browser cookies to COOKIE_FILE. Returns True on success.

    This is the one operation that can prompt for the login password.
    """
    if not COOKIE_BROWSER:
        return False
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "yt_dlp",
             "--cookies-from-browser", COOKIE_BROWSER,
             "--cookies", COOKIE_FILE,
             "--skip-download", "--simulate", "--quiet",
             "https://www.youtube.com/watch?v=BaW_jenozKc"],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    if os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        # Cookies are account credentials -- keep them owner-readable only.
        try:
            os.chmod(COOKIE_FILE, 0o600)
        except OSError:
            pass
        return True
    return proc.returncode == 0


def have_cookie_file():
    return os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0

JOBS = {}
JOBS_LOCK = threading.Lock()

PERCENT_RE = re.compile(r"\[download\]\s+([\d.]+)%")
DEST_RE = re.compile(r"(?:Destination|Merging formats into):?\s*\"?([^\"\n]+)\"?$")
SIZE_RE = re.compile(r"\[download\]\s+[\d.]+%\s+of\s+~?\s*([\d.]+\s?\S+?)(?:\s+at\s|\s+in\s|\s*$)")

# Default max resolution for video downloads when the user doesn't pick one.
DEFAULT_QUALITY = "1080"
VALID_QUALITIES = {"best", "2160", "1440", "1080", "720", "480"}


def build_command(url, mode, quality=DEFAULT_QUALITY, subs=False):
    base = [sys.executable, "-m", "yt_dlp", "--newline", "--no-playlist"]
    if JS_RUNTIME:
        # --remote-components fetches yt-dlp's challenge solver script, which
        # the runtime needs to answer YouTube's "n challenge". Without it the
        # extraction fails with "The page needs to be reloaded."
        base += ["--js-runtimes", JS_RUNTIME, "--remote-components", "ejs:github"]
    # Prefer the exported file: it needs no Keychain access, so no password
    # prompt. Fall back to reading the browser directly if it's missing.
    if have_cookie_file():
        base += ["--cookies", COOKIE_FILE]
    elif COOKIE_BROWSER:
        base += ["--cookies-from-browser", COOKIE_BROWSER]
    outtmpl = os.path.join(DEFAULT_OUTPUT_DIR, "%(title)s.%(ext)s")
    if mode == "audio":
        base += ["-x", "--audio-format", "mp3"]
    else:
        cap = None if quality not in VALID_QUALITIES or quality == "best" else quality
        if FFMPEG_AVAILABLE:
            if cap:
                fmt = f"bestvideo[height<={cap}]+bestaudio/best[height<={cap}]"
            else:
                fmt = "bv*+ba/b"
        else:
            fmt = f"best[height<={cap}]/b" if cap else "b"
        base += ["-f", fmt, "--merge-output-format", "mp4"]
        if subs:
            # Prefer real English captions; fall back to auto-generated ones
            # if that's all the video has. Saved as a separate .srt file
            # next to the video (converted from YouTube's vtt when ffmpeg
            # is available; left as .vtt otherwise).
            # "en.*" alone also matches en-orig and en-en, littering the
            # folder with near-identical files. Excluding those variants
            # leaves the single .srt the UI promises.
            base += ["--write-subs", "--write-auto-subs",
                     "--sub-langs", "en.*,-en-orig,-en-en"]
            if FFMPEG_AVAILABLE:
                base += ["--convert-subs", "srt"]
    base += ["-o", outtmpl, url]
    return base


def explain_failure(log):
    """Turn yt-dlp's raw output into a plain-English cause and fix.

    The generic "see log for details" hides the two failures that actually
    happen in practice: a missing JS runtime and YouTube's bot check.
    """
    text = "\n".join(log)
    if "Sign in to confirm" in text or "not a bot" in text:
        if COOKIE_BROWSER:
            return (
                f"YouTube blocked the request as a suspected bot, even using your "
                f"{COOKIE_BROWSER.title()} cookies. Open YouTube in {COOKIE_BROWSER.title()}, "
                "make sure you're signed in and can play the video, then try again."
            )
        return (
            "YouTube blocked the request as a suspected bot. This is fixed by "
            "sending your browser's cookies, but no supported browser was found. "
            "Install Chrome, Brave, Edge, Firefox, or Safari, sign in to YouTube "
            "there, then restart the downloader."
        )
    if "page needs to be reloaded" in text or "challenge solving failed" in text:
        return (
            "YouTube's player challenge couldn't be solved, so no downloadable "
            "formats were found. This usually clears up on its own — try again, "
            "and if it persists, relaunch to pick up the latest yt-dlp."
        )
    if "No supported JavaScript runtime" in text:
        return (
            "YouTube now needs a JavaScript runtime and none was found. "
            "Install one with: brew install deno (then relaunch the downloader)."
        )
    if "Video unavailable" in text or "private video" in text.lower():
        return "That video is unavailable, private, or removed."
    if "is not a valid URL" in text or "Unsupported URL" in text:
        return "That doesn't look like a valid video URL."
    # Fall back to yt-dlp's own last ERROR line, which beats a generic message.
    for line in reversed(log):
        if line.startswith("ERROR:"):
            return line[len("ERROR:"):].strip()
    return "yt-dlp exited with an error. See log for details."


def cookies_look_stale(log):
    """True if the failure looks like rejected/expired cookies."""
    text = "\n".join(log)
    return ("Sign in to confirm" in text or "not a bot" in text
            or "cookies are no longer valid" in text)


def run_ytdlp(job, cmd):
    """Run yt-dlp, streaming progress into `job`. Returns the exit code."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=DEFAULT_OUTPUT_DIR,
    )
    job["pid"] = proc.pid
    for line in proc.stdout:
        line = line.rstrip("\n")
        if not line:
            continue
        job["log"].append(line)
        job["log"] = job["log"][-80:]
        m = PERCENT_RE.search(line)
        if m:
            job["percent"] = float(m.group(1))
        s = SIZE_RE.search(line)
        if s:
            job["size"] = s.group(1).strip()
        d = DEST_RE.search(line)
        if d:
            job["filename"] = os.path.basename(d.group(1))
    proc.wait()
    return proc.returncode


def run_job(job_id, url, mode, quality=DEFAULT_QUALITY, subs=False):
    job = JOBS[job_id]

    if mode == "audio" and not FFMPEG_AVAILABLE:
        job["status"] = "error"
        job["error"] = (
            "MP3 extraction needs ffmpeg, which isn't installed. "
            "Install it with: brew install ffmpeg (then try again)."
        )
        return

    subs = subs and mode == "video"
    if subs and not FFMPEG_AVAILABLE:
        job["log"].append(
            "(ffmpeg not found - subtitles will be saved as .vtt instead of "
            ".srt. Install ffmpeg for automatic conversion.)"
        )

    job["status"] = "running"
    try:
        rc = run_ytdlp(job, build_command(url, mode, quality, subs))
        if rc != 0 and cookies_look_stale(job["log"]) and COOKIE_BROWSER:
            # The saved cookies stopped working -- usually because you signed
            # out of YouTube or changed your password. Refresh them once and
            # retry, so the only password prompt happens when it's genuinely
            # needed rather than on every download.
            job["log"].append(
                "(Saved cookies were rejected - refreshing them from "
                f"{COOKIE_BROWSER.title()}. macOS may ask for your password.)"
            )
            job["percent"] = 0
            if export_cookies():
                rc = run_ytdlp(job, build_command(url, mode, quality, subs))
        if rc == 0:
            job["status"] = "done"
            job["percent"] = 100
        else:
            job["status"] = "error"
            job["error"] = explain_failure(job["log"])
    except FileNotFoundError:
        job["status"] = "error"
        job["error"] = "yt-dlp isn't installed. Re-run the launcher to install it."
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)


INDEX_HTML_PATH = os.path.join(SCRIPT_DIR, "index.html")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            try:
                with open(INDEX_HTML_PATH, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                body = b"<h1>index.html missing</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/status":
            qs = parse_qs(parsed.query)
            job_id = qs.get("id", [None])[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                data = dict(job) if job else None
            if data is None:
                self._send_json({"error": "unknown job"}, 404)
            else:
                self._send_json(data)
        elif parsed.path == "/api/info":
            self._send_json({
                "output_dir": DEFAULT_OUTPUT_DIR,
                "ffmpeg_available": FFMPEG_AVAILABLE,
                "default_quality": DEFAULT_QUALITY,
                "js_runtime": JS_RUNTIME,
                "cookie_browser": COOKIE_BROWSER,
                "cookies_saved": have_cookie_file(),
            })
        elif parsed.path == "/api/open-folder":
            try:
                subprocess.Popen(["open", DEFAULT_OUTPUT_DIR])
            except Exception:
                pass
            self._send_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/download":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                payload = {}
            url = (payload.get("url") or "").strip()
            mode = payload.get("mode") if payload.get("mode") in ("video", "audio") else "video"
            quality = payload.get("quality")
            if quality not in VALID_QUALITIES:
                quality = DEFAULT_QUALITY
            subs = bool(payload.get("subs"))
            if not url:
                self._send_json({"error": "Missing URL"}, 400)
                return
            job_id = uuid.uuid4().hex[:12]
            with JOBS_LOCK:
                JOBS[job_id] = {
                    "id": job_id, "url": url, "mode": mode, "quality": quality,
                    "subs": subs, "status": "starting", "percent": 0, "size": None,
                    "log": [], "filename": None, "error": None,
                }
            t = threading.Thread(target=run_job, args=(job_id, url, mode, quality, subs), daemon=True)
            t.start()
            self._send_json({"id": job_id})
        else:
            self.send_response(404)
            self.end_headers()


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"YouTube Downloader running at {url}")
    print(f"Saving downloads to: {DEFAULT_OUTPUT_DIR}")
    if not FFMPEG_AVAILABLE:
        print("NOTE: ffmpeg not found - video quality will be limited and MP3 "
              "extraction will not work. Install with: brew install ffmpeg")
    if JS_RUNTIME:
        print(f"JavaScript runtime: {JS_RUNTIME}")
    else:
        print("NOTE: no JavaScript runtime found - YouTube downloads will fail. "
              "Install one with: brew install deno")
    if COOKIE_BROWSER:
        print(f"Using cookies from: {COOKIE_BROWSER}")
    else:
        print("NOTE: no supported browser found for cookies - YouTube may block "
              "downloads with a bot check.")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
