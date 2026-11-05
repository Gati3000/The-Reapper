# The Reapper

Web interface for downloading premium music with lyrics and covers. It wraps [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) and a wrapper that logs in to your account ([WorldObservationLog/wrapper](https://github.com/WorldObservationLog/wrapper) releases, see [Credits](#credits)).

## Requirements

- Linux: Debian, Ubuntu or WSL, with root access and Python 3.8+
- Installed for you: Go, GPAC, Bento4, ffmpeg, Flask, PyYAML, the wrapper and the downloader

## Installation

```bash
git clone https://github.com/Gati3000/The-Reapper.git
cd The-Reapper
sudo python3 App/Launcher/Start.py update
sudo ln -s "$(pwd)/App/Launcher/rip" /usr/local/bin/rip
```

The last line adds the optional `rip` command used below.

## Commands

| Command | What it does |
| --- | --- |
| `rip -h` | Shows the help (also shown by `rip` alone) |
| `rip -up` | Checks the installation and starts the web UI |
| `rip -check` | Only reports what is missing or outdated |
| `sudo rip -update` | Updates the project code, then installs or updates components after asking |
| `sudo rip -update -y` | Same, without questions |
| `sudo rip -update -b` | Switches to the Beta branch, then updates |
| `rip upgrade` | Updates only the project code. Add `--force` to discard local changes, `-b` to switch to Beta, `-y` to skip questions |
| `rip -log` | Starts writing `User/reapper.log` (works in a running UI) |
| `rip -log -stop` | Stops writing the log file |
| `sudo rip -rm` | Removes the program, keeps `User/` settings and music in a backup folder |
| `sudo rip -rm -f` | Removes everything including settings, music stays in a backup (`rip purge` does the same) |

Aliases: `run` = `-up`, `check` = `-check`, `update` and `install` = `-update`, `uninstall` = `-rm`, `log` = `-log`. Without `rip` you can use `python3 Main.py` to start the UI, `sudo python3 App/Launcher/Start.py update` to update components and `python3 App/Launcher/Manage.py` for self-update and removal.

## Your data

Everything personal lives in `User/`: `config.yaml` (downloader settings, created from `Example-Config.yaml`), `.credentials` (saved login, optional), `prefs.json` (main page preferences) and `reapper.log` (only while `rip -log` is on).

## Updating and uninstalling

`rip -update` checks Go, the downloader, the wrapper, Bento4, GPAC and system packages. Sources and versions are pinned in `App/Manifest.ini` and fall back to `App/Defaults.ini`. If launcher files changed, run `sudo rip -update` once more, then restart the UI.

`rip -rm` removes the program folder, downloader, wrapper, Bento4 and the links in `/usr/local/bin`. Your `User/` folder and downloads inside the project go to `~/The-Reapper-backup-<date>`. `rip -rm -f` also deletes settings and saved login (you type `delete` to confirm). Go, GPAC, ffmpeg and other system packages stay.

### Credits

# The Reapper is only a convenience layer. All the real work is done by the tools below, so thanks to:

- [@lalit22km](https://github.com/Gati3000/alac-rip-gati/commits?author=lalit22km) for [alac-rip](https://github.com/lalit22km/alac-rip), the original web interface this project builds on.
- [@zhaarey](https://github.com/zhaarey) for [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader), the downloader that does all the downloading.
- [@zhaarey](https://github.com/zhaarey) for [wrapper](https://github.com/zhaarey/wrapper), which handles the account login and session.

## Disclaimer

This tool is for educational purposes and personal use only. Respect Apple's Terms of Service and only download content you have the legal right to access. The authors are not responsible for any misuse of the underlying tools.

