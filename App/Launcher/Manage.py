#!/usr/bin/env python3
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parent
PROJECT_DIR = LAUNCHER_DIR.parent.parent
USER_DIR = PROJECT_DIR / "User"
AMD_DIR = PROJECT_DIR / "apple-music-downloader"
CONFIG_FILE = USER_DIR / "config.yaml"
SYSTEM_BIN = Path("/usr/local/bin")
SAVE_FOLDER_KEYS = ("alac-save-folder", "atmos-save-folder", "aac-save-folder", "mv-save-folder")
WATCHED_FILES = ("Manifest.ini", "Start.py", "Manage.py")


def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def inside(path, root):
    try:
        return os.path.commonpath([os.path.normpath(path), os.path.normpath(root)]) == os.path.normpath(root)
    except ValueError:
        return False


def human(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def dir_size(path, skip=()):
    total = 0
    for base, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if Path(base, d) not in skip]
        for name in files:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
    return total


def owner_home():
    name = os.environ.get("SUDO_USER")
    if name and name != "root":
        try:
            return Path(pwd.getpwnam(name).pw_dir)
        except KeyError:
            pass
    return Path.home()


def project_is_sane():
    return ((PROJECT_DIR / "Main.py").is_file()
            and (LAUNCHER_DIR / "Start.py").is_file()
            and len(PROJECT_DIR.parts) >= 3
            and PROJECT_DIR != Path.home())


def ask(question):
    try:
        return input(question).strip().lower()
    except EOFError:
        return ""

def git(*args):
    cmd = ["git", "-c", f"safe.directory={PROJECT_DIR}", "-C", str(PROJECT_DIR), *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def cmd_self_update(force=False, assume_yes=False):
    if not (PROJECT_DIR / ".git").exists():
        print("This folder is not a git clone, so it cannot update itself.")
        return 1
    if is_root() and PROJECT_DIR.stat().st_uid != 0:
        print("This folder belongs to another user. Run without sudo so the files keep their owner.")
        return 1

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch in ("", "HEAD"):
        print("No branch is checked out (detached HEAD). Run: git switch <branch>")
        return 1
    tracked = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    upstream = tracked.stdout.strip() if tracked.returncode == 0 else f"origin/{branch}"

    print(f"Branch {branch}, comparing with {upstream}")
    fetched = git("fetch", "--prune", "origin")
    if fetched.returncode != 0:
        print(f"Could not reach GitHub: {fetched.stderr.strip()}")
        return 1
    if git("rev-parse", "--verify", "-q", upstream).returncode != 0:
        print(f"{upstream} does not exist on GitHub.")
        return 1

    ahead, behind = map(int, git("rev-list", "--left-right", "--count", f"HEAD...{upstream}").stdout.split())
    dirty = git("status", "--porcelain", "--untracked-files=no").stdout.strip()

    if ahead == 0 and behind == 0:
        print("Already up to date.")
        return 0
    if behind == 0:
        print(f"Nothing to pull. You have {ahead} local commit(s) that are not pushed yet (git push).")
        return 0

    print(f"\n{behind} new commit(s) on GitHub:")
    print(git("log", "--oneline", "-10", f"HEAD..{upstream}").stdout.rstrip())

    diverged = ahead > 0
    if diverged and not force:
        print(f"\nYour history and GitHub's have diverged ({ahead} local commit(s) not on GitHub).")
        print("To make this folder match GitHub exactly, run: rip -update --force")
        print("That discards local commits and edits to tracked files. User/ is never touched.")
        return 1
    if dirty and not force:
        print("\nYou have local changes in tracked files:")
        print(dirty)
        print("Commit or stash them first, or run: rip -update --force (discards them)")
        return 1

    if not assume_yes:
        warning = " This discards local commits and changes." if (force and (dirty or diverged)) else ""
        if ask(f"\nUpdate now?{warning} [y/N] ") not in ("y", "yes"):
            print("Nothing changed.")
            return 0

    old = git("rev-parse", "HEAD").stdout.strip()
    result = git("reset", "--hard", upstream) if force else git("merge", "--ff-only", upstream)
    if result.returncode != 0:
        print(f"Update failed: {result.stderr.strip() or result.stdout.strip()}")
        return 1

    changed = git("diff", "--name-only", old, "HEAD").stdout.split()
    print("\nUpdated.")
    if any(Path(name).name in WATCHED_FILES for name in changed) and not os.environ.get("REAPPER_CHAIN"):
        print("Launcher files changed. Run: sudo rip -update")
    print("Restart the web UI to load the new code.")
    return 0

def music_folders():
    """Download folders from config.yaml that live inside the project."""
    try:
        text = CONFIG_FILE.read_text()
    except OSError:
        return []
    found = []
    for key in SAVE_FOLDER_KEYS:
        match = re.search(rf"^{key}:[ \t]*(.*)$", text, re.MULTILINE)
        if not match:
            continue
        value = re.sub(r"\s+#.*$", "", match.group(1)).strip().strip("\"'")
        if not value:
            continue
        path = Path(value)
        path = Path(os.path.normpath(path if path.is_absolute() else AMD_DIR / path))
        if inside(path, PROJECT_DIR) and path.is_dir() and any(path.iterdir()) and path not in found:
            found.append(path)
    return [p for p in found if not any(q != p and inside(p, q) for q in found)]


def project_links():
    """Symlinks in /usr/local/bin that point into the project (Bento4 tools, rip)."""
    if not SYSTEM_BIN.is_dir():
        return []
    links = []
    for entry in SYSTEM_BIN.iterdir():
        if entry.is_symlink():
            target = os.readlink(entry)
            if os.path.isabs(target) and inside(target, PROJECT_DIR):
                links.append(entry)
    return sorted(links)


def remove_links(links):
    for link in links:
        try:
            link.unlink()
        except OSError as e:
            print(f"WARN: Could not remove {link}: {e}")


def remove_project():
    if inside(os.getcwd(), PROJECT_DIR):
        os.chdir("/")
    errors = []
    shutil.rmtree(PROJECT_DIR, onerror=lambda func, path, exc: errors.append(path))
    return errors


def make_backup_dir():
    backup = owner_home() / f"The-Reapper-backup-{time.strftime('%Y%m%d-%H%M%S')}"
    backup.mkdir(parents=True)
    name = os.environ.get("SUDO_USER")
    if name and name != "root":
        try:
            info = pwd.getpwnam(name)
            os.chown(backup, info.pw_uid, info.pw_gid)
        except (KeyError, OSError):
            pass
    return backup


def move_music_to_backup(music, backup=None):
    backup = backup or make_backup_dir()
    for index, folder in enumerate(music):
        target = backup / "Downloads" / (f"{index}-{folder.name}" if index else folder.name)
        target.parent.mkdir(exist_ok=True)
        shutil.move(str(folder), str(target))
    return backup


def cmd_uninstall(assume_yes=False):
    if not is_root():
        print("Needs root. Run: sudo rip -rm")
        return 1
    if not project_is_sane():
        print(f"Refusing to remove {PROJECT_DIR}: it does not look like a The Reapper folder.")
        return 1

    music, links = music_folders(), project_links()
    keep = [USER_DIR] if USER_DIR.exists() else []
    program_size = dir_size(PROJECT_DIR, skip=set(keep) | set(music))

    print(f"Uninstall The Reapper from {PROJECT_DIR}\n")
    print(f"Will remove: the program folder ({human(program_size)}), downloader, wrapper and Bento4")
    for link in links:
        print(f"             link {link}")
    if keep or music:
        print("\nWill keep (moved to a backup folder in your home directory):")
        if keep:
            print(f"  - settings (User/, {human(dir_size(USER_DIR))})")
        for folder in music:
            print(f"  - downloads in {folder} ({human(dir_size(folder))})")
    print("\nNot removed: Go, GPAC, ffmpeg and other system packages (other programs may use them).")

    if not assume_yes and ask("\nContinue? [y/N] ") not in ("y", "yes"):
        print("Nothing changed.")
        return 0

    backup = None
    if keep or music:
        backup = make_backup_dir()
        if keep:
            shutil.move(str(USER_DIR), str(backup / "User"))
        if music:
            move_music_to_backup(music, backup)
    remove_links(links)
    errors = remove_project()

    print("\nRemoved.")
    if errors:
        print(f"WARN: {len(errors)} file(s) could not be removed, check {PROJECT_DIR}")
    if backup:
        print(f"Settings and downloads were moved to: {backup}")
        print("To restore settings after a fresh clone:")
        print(f"  mkdir -p <new folder>/User && cp -a {backup}/User/. <new folder>/User/")
    print("If your shell was inside the removed folder, run: cd ~")
    return 0


def cmd_purge(assume_yes=False):
    if not is_root():
        print("Needs root. Run: sudo rip -rm -f")
        return 1
    if not project_is_sane():
        print(f"Refusing to remove {PROJECT_DIR}: it does not look like a The Reapper folder.")
        return 1

    music, links = music_folders(), project_links()
    program_size = dir_size(PROJECT_DIR, skip=set(music))
    print(f"Remove The Reapper from {PROJECT_DIR} including your settings\n")
    print(f"Will remove: the program folder ({human(program_size)}), downloader, wrapper and Bento4")
    if USER_DIR.exists():
        print(f"             your settings and saved login (User/, {human(dir_size(USER_DIR))}), no backup")
    for link in links:
        print(f"             link {link}")
    if music:
        print("\nWill keep (moved to a backup folder in your home directory):")
        for folder in music:
            print(f"  - downloads in {folder} ({human(dir_size(folder))})")
    print("\nNot removed: Go, GPAC, ffmpeg and other system packages (other programs may use them).")

    if not assume_yes and ask("\nSettings cannot be restored. Type 'delete' to confirm: ") != "delete":
        print("Nothing changed.")
        return 0

    backup = move_music_to_backup(music) if music else None
    remove_links(links)
    errors = remove_project()
    print("\nRemoved.")
    if errors:
        print(f"WARN: {len(errors)} file(s) could not be removed, check {PROJECT_DIR}")
    if backup:
        print(f"Downloads were moved to: {backup}")
    print("If your shell was inside the removed folder, run: cd ~")
    return 0


def main(argv):
    command = argv[0] if argv else ""
    flags = set(argv[1:])
    yes = bool(flags & {"-y", "--yes"})
    if command in ("self-update", "upgrade"):
        return cmd_self_update(force="--force" in flags, assume_yes=yes)
    if command == "uninstall":
        if flags & {"-f", "--full"}:
            return cmd_purge(assume_yes=yes)
        return cmd_uninstall(assume_yes=yes)
    if command == "purge":
        return cmd_purge(assume_yes=yes)
    print("Usage: Manage.py [self-update [--force] [-y] | uninstall [-f] [-y]]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
