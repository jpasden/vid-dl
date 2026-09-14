# vid-dl

A tiny local web app for downloading YouTube videos and audio, built on top of [yt-dlp](https://github.com/yt-dlp/yt-dlp). Paste a link, pick a format, click Download — no terminal commands to type.

## Disclaimer

This project is **not affiliated with, endorsed by, or connected to YouTube or Google** in any way.

It is a personal-use automation tool that installs and drives a local copy of the open-source `yt-dlp` project. Downloading video you don't have the rights to may violate YouTube's Terms of Service and/or copyright law, depending on your jurisdiction and how you use the content. **You are responsible for how you use this tool** — only download content you own, have permission to use, or that is otherwise licensed for download (e.g. Creative Commons, public domain, or your own uploads).

This repository does **not** include or redistribute yt-dlp itself. It is downloaded directly from [PyPI](https://pypi.org/project/yt-dlp/) the first time you run the launcher, under yt-dlp's own license (The Unlicense), and is kept up to date automatically on every subsequent run.

## Features

- Video (MP4) or audio-only (MP3) downloads
- Quality picker: Best, 4K, 2K, 1080p (default), 720p, 480p
- Optional English subtitles (`.srt`), with automatic fallback to auto-generated captions if no human-made ones exist
- Live progress bar with total file size
- Plain browser UI — no command line typing after setup
- Checks for and installs yt-dlp updates automatically on every launch

## Requirements

- **macOS** with **Python 3** (already included on modern macOS; otherwise install from [python.org](https://www.python.org/downloads/))
- **A JavaScript runtime** — **required.** See [JavaScript runtime
  (Deno or Node)](#javascript-runtime-deno-or-node) below for which to pick
  and how to install it. Without one, every download fails.
- **A signed-in browser** — Chrome, Brave, Edge, Firefox, or Safari. The app
  reads its YouTube cookies to get past YouTube's bot check. See
  [About the password prompt](#about-the-password-prompt) — macOS asks once.
- **[ffmpeg](https://ffmpeg.org)** — optional but recommended. Needed for MP3 extraction and for merging separate video/audio streams into the best-quality MP4. Without it, video quality is capped to formats that don't require merging, and MP3 downloads won't work.
  - Install with Homebrew: `brew install ffmpeg` (get Homebrew first at [brew.sh](https://brew.sh) if you don't have it)
- **yt-dlp** — installed automatically the first time you run the app. You don't need to install it yourself.

## JavaScript runtime (Deno or Node)

YouTube now scrambles its video links with a JavaScript puzzle that has to be
run to be solved. That means a JavaScript runtime is **required** — this app
cannot download anything without one. You only need **one** of the options
below, and you never have to configure it: the app detects whatever is
installed and uses it automatically.

### Which one should I install?

**Install Deno** unless you already have Node.js. It's a single self-contained
binary, it's what yt-dlp prefers, and it won't interfere with anything else on
your Mac.

```bash
brew install deno
```

(No Homebrew? Get it at [brew.sh](https://brew.sh) first, or install Deno
directly with `curl -fsSL https://deno.land/install.sh | sh`.)

**Already have Node.js?** Then you're done — nothing to install. Many people
have it from other development work. Check with:

```bash
node --version
```

If that prints a version number, this app will find and use it.

The app checks for runtimes in the same order yt-dlp prefers them — **deno**,
**node**, **quickjs**, **bun** — and uses the first one it finds. If you have
several, that's fine; there's no conflict and nothing to choose between.

### Checking that it worked

Start the app. The terminal window prints which runtime it found:

```
JavaScript runtime: deno
Using cookies from: chrome
```

If instead you see this, the runtime isn't installed or isn't on your `PATH`:

```
NOTE: no JavaScript runtime found - YouTube downloads will fail.
```

### Troubleshooting

**"I installed Deno but it still says no runtime found."** Your shell needs to
pick up the new command. Quit and reopen Terminal, then run `deno --version`
to confirm it's there before relaunching the app.

**"Sign in to confirm you're not a bot."** This is usually the runtime, not
your account — install Deno as above. If it persists with a runtime installed,
open YouTube in your browser, make sure you're signed in and the video plays,
then try again.

**"The page needs to be reloaded."** YouTube changed its puzzle and yt-dlp
needs to catch up. Relaunch `Start YouTube Downloader.command`, which upgrades
yt-dlp automatically, and try again.

## About the password prompt

The first time you download something, macOS will ask for your password with a
dialog mentioning your **Keychain**. This is expected. Here's exactly what's
happening, so you can judge it for yourself:

YouTube blocks anonymous downloads with a "Sign in to confirm you're not a bot"
error. Getting past it means sending the YouTube cookies from your browser,
which prove you're a real signed-in person. macOS encrypts browser cookies and
asks permission before releasing them — that's the prompt you're seeing.

- It's your **Mac login password**, not an administrator/install prompt.
- Nothing is sent anywhere. The cookies go to YouTube, to authenticate your own
  download, exactly as your browser would send them.
- Your cookies are saved to `.cookies.txt` next to the app so it only has to
  ask once. That file is git-ignored and readable only by your account.

After the first time you shouldn't be asked again. If you sign out of YouTube
or change your Google password, the saved cookies stop working — the app
detects this, refreshes them automatically, and macOS asks once more.

**Don't want this at all?** Delete `.cookies.txt` and the app falls back to
reading the browser directly (which prompts each time), or remove the cookie
handling entirely — downloads will work for videos YouTube doesn't gate, and
fail with the bot-check error for the rest.

## Installation

1. Clone or download this repository:

   ```bash
   git clone https://github.com/jpasden/vid-dl.git
   ```

2. Open the folder in Finder.
3. Double-click **`Start YouTube Downloader.command`**.
   - The first time, macOS may warn that it's from an unidentified developer. Right-click the file → **Open**, then confirm, to bypass this once.
   - The launcher installs `yt-dlp` automatically if it isn't already present, and checks for updates every time you run it afterward.

## Usage

1. Running the launcher opens a page in your browser at `http://127.0.0.1:8642`.
2. Paste a YouTube video URL.
3. Choose **Video (MP4)** or **Audio only (MP3)**.
4. Pick a max quality (1080p by default).
5. Leave **"Download English subtitles"** checked if you want a `.srt` file saved alongside the video.
6. Click **Download** and watch the progress bar (shows percent complete and total file size).
7. Files are saved to `~/Downloads/YT` by default — click **"Open downloads folder"** to jump there.
8. When you're done, close the Terminal window (or press `Ctrl+C` in it) to stop the app.

## How it works

`server.py` is a small Python script (standard library only, no extra dependencies) that runs a local web server, wraps the `yt-dlp` command-line tool, and serves the front end in `index.html`. Everything runs locally on your machine — no data is sent anywhere except to YouTube itself to fetch the video you asked for.

## License

The wrapper/UI code in this repository is licensed under the MIT License — see [LICENSE](LICENSE).

`yt-dlp`, which this tool installs and calls at runtime, is licensed separately under [The Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE) and is not included in this repository.
