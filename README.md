# The Reapper

Web interface for downloading premium music with lyrics and covers. It wraps [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) and a wrapper that logs in to your account ([WorldObservationLog/wrapper](https://github.com/WorldObservationLog/wrapper) releases, see [Credits](#credits)).

## Requirements

- Linux: Debian, Ubuntu or WSL
- Root access (needed for installing and updating components)
- Python 3.8+

Program installs for you:
-Go
-Gpac
-Bento4
-ffmpeg
-Flask
-PyYAML
-Wrapper and AMD

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
| `rip` (or `rip -up`, `rip run`) | Checks the installation and starts the web UI |
| `rip check` | Only reports what is missing or outdated |
| `sudo rip update` | Updates the project code from GitHub, then lists missing and outdated components, asks, and installs or updates them |
| `sudo rip update -y` | Same, without the questions |
| `rip upgrade` | Updates only the project code (`git` fast-forward). Add `--force` to discard local changes and match GitHub exactly |
| `sudo rip -rm` | Removes the program, keeps your settings and downloads in a backup folder (see [Uninstalling](#uninstalling)) |
| `sudo rip -rm -f` | Removes everything including your settings, downloads are still kept in a backup |

`-update`, `install` and `-check` work as aliases of `update` and `check`.

Without the command: `python3 Main.py` starts the UI, `sudo python3 App/Launcher/Start.py update` installs and updates components, and `python3 App/Launcher/Manage.py` handles self-update and removal.

Without the command: `python3 Main.py` starts the UI and `sudo python3 App/Launcher/Start.py update` updates.

The UI listens on `http://<host>:5000`. Change it with the `REAPPER_HOST` and `REAPPER_PORT` environment variables, for example `REAPPER_HOST=127.0.0.1` to keep it local. The pages are responsive and work on phones.

1. Log in to the wrapper on the main page (email, password and the 2FA code if your account asks for it). You can save the login for automatic sign-in on the next start.
2. Paste an album, playlist or song link.
3. Pick the format: standard download (ALAC), or turn on **Special audio** and choose **ATMOS** or **AAC**. Your choice is remembered.
4. Follow the live logs. The **Settings** page edits the downloader configuration.

> **Security:** the UI has no login of its own and listens on all interfaces by default. Run it only on a network you trust, or set `REAPPER_HOST=127.0.0.1`, or put it behind a reverse proxy with authentication. Saved logins are only base64 encoded (not encrypted) and the file is readable by its owner only (`chmod 600`).

## Your data

Everything personal lives in `User/`:

- `config.yaml`: downloader settings. Created from `Example-Config.yaml` on first run and edited on the Settings page. The downloader reads it through a link, so there is only one copy.
- `.credentials`: saved login, only if you choose to save it.
- `prefs.json`: format preferences from the main page.

Fill in `media-user-token` and `storefront` in the settings before downloading.

## Updating

`sudo rip update` first updates the project code, then checks Go, the downloader branch, the wrapper release, Bento4, GPAC and the system packages (git, ffmpeg, wget, Flask, PyYAML). Versions of Bento4, GPAC and the download sources are pinned in `App/Launcher/Manifest.ini`; change a value there and run `rip update` to apply it.

If launcher files changed in the update, run `sudo rip update` once more so the new version of the launcher is used. Restart the web UI to load new code.

## Uninstalling

- `sudo rip -rm` removes the program folder, the downloader, the wrapper, Bento4 and the links in `/usr/local/bin`. Your `User/` folder and downloads that live inside the project are moved to `~/The-Reapper-backup-<date>`.
- `sudo rip -rm -f` does the same but also deletes your settings and saved login, with no backup of them. You have to type `delete` to confirm.

Go, GPAC, ffmpeg and other system packages are not removed because other programs may use them. To restore settings after a fresh clone, copy the backed up `User/` folder into the new project folder.

### Credits

# The Reapper is only a convenience layer. All the real work is done by the tools below, so thanks to:

- [@lalit22km](https://github.com/Gati3000/alac-rip-gati/commits?author=lalit22km) for [alac-rip](https://github.com/lalit22km/alac-rip), the original web interface this project builds on.
- [@zhaarey](https://github.com/zhaarey) for [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader), the downloader that does all the downloading.
- [@zhaarey](https://github.com/zhaarey) for [wrapper](https://github.com/zhaarey/wrapper), which handles the account login and session.

## Disclaimer

This tool is for educational purposes and personal use only. Respect Apple's Terms of Service and only download content you have the legal right to access. The authors are not responsible for any misuse of the underlying tools.
