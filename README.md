# The Reapper

Web interface for downloading premium music with lyrics and covers. It wraps [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) and the wrapper that logs in to your account.

## Requirements

- Linux: Debian, Ubuntu or WSL
- Root access (needed for installing and updating components)
- Python 3.8+

Everything else (Go, GPAC, Bento4, ffmpeg, the wrapper and the downloader) is installed for you.

## Installation

```bash
git clone https://github.com/Gati3000/The-Reapper.git
cd The-Reapper
sudo python3 App/Launcher/Start.py update
```

Optional: add the `rip` command.

```bash
sudo ln -s "$(pwd)/App/Launcher/rip" /usr/local/bin/rip
```

## Usage

| Command | What it does |
| --- | --- |
| `rip` | Checks the installation and starts the web UI |
| `sudo rip update` | Lists missing and outdated components, asks, then installs or updates them |
| `sudo rip update -y` | Same, without the question |
| `rip check` | Only reports what is missing |

Without the command: `python3 Main.py` starts the UI and `sudo python3 App/Launcher/Start.py update` updates.

The UI listens on `http://<host>:5000`. Change it with the `REAPPER_HOST` and `REAPPER_PORT` environment variables, for example `REAPPER_HOST=127.0.0.1` to keep it local. The pages are responsive and work on phones.

## Project layout

```
Main.py                  Checks everything is installed, then starts the UI
App/
  Routes.py              Web routes
  Launcher/
    Start.py             Install, check and update logic
    Manifest.ini         Pinned versions and download sources
    Example-Config.yaml  Template for the downloader settings
    rip                  Command line helper
  Static/                Theme.css and icons
  Templates/             Home.html and Settings.html
User/                    Your settings, created at runtime, not in git
```

## Your data

Everything personal lives in `User/`:

- `config.yaml`: downloader settings. Created from `Example-Config.yaml` on first run and edited on the Settings page. The downloader reads it through a link, so there is only one copy.
- `.credentials`: saved login, only if you choose to save it.
- `prefs.json`: format preferences from the main page.

Fill in `media-user-token` and `storefront` in the settings before downloading.

## Updating

`rip update` checks Go, the downloader branch, the wrapper release, Bento4 and GPAC. Versions of Bento4, GPAC and the download sources are pinned in `App/Launcher/Manifest.ini`; change a value there and run `rip update` to apply it.

## Disclaimer

This tool is for educational purposes and personal use only. Respect Apple's Terms of Service and only download content you have the legal right to access. The authors are not responsible for any misuse of the underlying tools.
