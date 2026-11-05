"""Launcher for The Reapper: installs, checks and updates components.

Standard library only, so it runs before any dependency is installed."""
import configparser
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from urllib.parse import urlparse
import zipfile
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from App.Paths import *

USER_AGENT = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
STATUS_OK, STATUS_MISSING, STATUS_OUTDATED, STATUS_NEWER = "ok", "missing", "outdated", "newer"

MANIFEST_SECTION = "manifest"

def _read_ini(path):
    cp = configparser.ConfigParser(interpolation=None)
    try:
        if not cp.read(path) or not cp.has_section(MANIFEST_SECTION):
            return None
    except configparser.Error:
        return None
    return {key: val.strip() for key, val in cp[MANIFEST_SECTION].items() if val.strip()}

DEFAULTS = _read_ini(DEFAULTS_FILE)
if not DEFAULTS:
    raise SystemExit(f"ERROR: {DEFAULTS_FILE.name} is missing or broken. Restore it with: rip upgrade --force")

def load_manifest():
    """Return the manifest values; Manifest.ini overrides Defaults.ini."""
    values = dict(DEFAULTS)
    override = _read_ini(MANIFEST_FILE)
    if override is None:
        print(f"WARN: no usable [{MANIFEST_SECTION}] in {MANIFEST_FILE.name}, using {DEFAULTS_FILE.name}")
        return values
    for key, val in override.items():
        if key in values:
            values[key] = val
    return values

MANIFEST = load_manifest()

def parse_version(text):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None

def fmt(version):
    return ".".join(map(str, version)) if version else "none"

try:
    GO_MIN_VERSION = parse_version(MANIFEST["go_min_version"]) or parse_version(DEFAULTS["go_min_version"])
except ValueError:
    GO_MIN_VERSION = parse_version(DEFAULTS["go_min_version"])

ARCH = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())

def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0

def setup_path():
    """Put Go, Bento4 and the wrapper on PATH for this process."""
    extra = [str(GO_ROOT / "bin"), str(WRAPPER_DIR)]
    bin_dir = bento4_bin_dir()
    if bin_dir:
        extra.append(str(bin_dir))
    os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])

def bento4_bin_dir() -> Optional[Path]:
    candidates = sorted(BENTO4_DIR.glob("Bento4*")) if BENTO4_DIR.exists() else []
    bin_dir = candidates[0] / "bin" if candidates else None
    return bin_dir if bin_dir and bin_dir.exists() else None

def run(cmd, **kwargs):
    return subprocess.run(cmd, **kwargs)

def download(url, dest, timeout=120):
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)

def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def verify_sha256(path, expected, label):
    actual = file_sha256(path)
    if not expected:
        print(f"WARN: no checksum available for {label}, its SHA-256 is {actual}")
        return
    if actual != expected.strip().lower():
        raise RuntimeError(f"Checksum mismatch for {label}: expected {expected}, got {actual}")
    print(f"INFO: {label} SHA-256 verified")

def fetch_json(url, timeout=20):
    text = fetch_text(url, timeout) if url else None
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None

def go_expected_sha(filename):
    releases = fetch_json(MANIFEST.get("go_checksums_url"))
    if not isinstance(releases, list):
        return None
    for release in releases:
        for entry in release.get("files", []):
            if entry.get("filename") == filename:
                return entry.get("sha256")
    return None

def github_asset_sha(download_url):
    parts = urlparse(download_url).path.strip("/").split("/")
    if len(parts) < 6 or parts[2:4] != ["releases", "download"]:
        return None
    owner, repo, tag, asset = parts[0], parts[1], parts[4], parts[5]
    release = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}")
    if not isinstance(release, dict):
        return None
    for entry in release.get("assets", []):
        digest = entry.get("digest") or ""
        if entry.get("name") == asset and digest.startswith("sha256:"):
            return digest.split(":", 1)[1]
    return None

def fetch_text(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers=USER_AGENT)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode()
    except Exception:
        return None

def remote_tags(repo_url):
    """Return the tag names of a git repository, or [] when offline."""
    try:
        out = run(["git", "ls-remote", "--tags", "--refs", repo_url],
                  capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.split("refs/tags/")[-1] for line in out.splitlines() if "refs/tags/" in line]

def _amd_config_is_default():
    """True when the downloader's config.yaml is the untouched tracked file."""
    git = ["git", "-C", str(AMD_DIR)]
    tracked = run([*git, "ls-files", "--error-unmatch", "config.yaml"], capture_output=True).returncode == 0
    clean = run([*git, "diff", "--quiet", "--", "config.yaml"], capture_output=True).returncode == 0
    return tracked and clean

def link_config():
    """Make apple-music-downloader/config.yaml point to User/config.yaml."""
    if not AMD_DIR.exists() or not CONFIG_FILE.exists():
        return
    if AMD_CONFIG.is_symlink() and AMD_CONFIG.resolve() == CONFIG_FILE.resolve():
        return
    try:
        if AMD_CONFIG.is_symlink() or AMD_CONFIG.exists():
            AMD_CONFIG.unlink()
        AMD_CONFIG.symlink_to(CONFIG_FILE)
    except OSError:
        shutil.copyfile(CONFIG_FILE, AMD_CONFIG)

def fill_wrapper_ports(path):
    text = path.read_text()
    new = re.sub(r"^decrypt-m3u8-port:[ \t]*(''|\"\")?[ \t]*$", 'decrypt-m3u8-port: "127.0.0.1:10020"', text, flags=re.MULTILINE)
    new = re.sub(r"^get-m3u8-port:[ \t]*(''|\"\")?[ \t]*$", 'get-m3u8-port: "127.0.0.1:20020"', new, flags=re.MULTILINE)
    if new != text:
        path.write_text(new)

def prepare_user_data():
    """Create User/, migrate settings from older layouts, make sure config.yaml exists."""
    USER_DIR.mkdir(exist_ok=True)

    old_credentials = PROJECT_DIR / ".credentials"
    if old_credentials.is_file() and not CREDENTIALS_FILE.exists():
        shutil.move(str(old_credentials), str(CREDENTIALS_FILE))
        print("INFO: Moved .credentials to User/")

    if not CONFIG_FILE.exists():
        existing = AMD_CONFIG if AMD_CONFIG.is_file() and not AMD_CONFIG.is_symlink() else None
        if existing and not _amd_config_is_default():
            shutil.copyfile(existing, CONFIG_FILE)
            print("INFO: Moved existing downloader settings to User/config.yaml")
        elif EXAMPLE_CONFIG.exists():
            shutil.copyfile(EXAMPLE_CONFIG, CONFIG_FILE)
            print("INFO: Created User/config.yaml from Example-Config.yaml")
    if CONFIG_FILE.exists():
        try:
            fill_wrapper_ports(CONFIG_FILE)
        except OSError as e:
            print(f"WARN: Could not update config.yaml: {e}")
        link_config()

# Components installersing 
def _apt():
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    cmd = ["apt-get", "-y", "-o", "Acquire::Retries=3", "-o", "Dpkg::Lock::Timeout=60"]
    return cmd, env

def install_system_packages():
    apt, env = _apt()
    run([*apt, "update"], check=True, env=env)
    run([*apt, "install", *MANIFEST["apt_packages"].split()], check=True, env=env)
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        install_static_ffmpeg()

def install_static_ffmpeg():
    if not ARCH:
        raise RuntimeError(f"No static ffmpeg build for {platform.machine()}")
    url = MANIFEST["ffmpeg_static_url"].format(arch=ARCH)
    tmp = Path(tempfile.mkdtemp(prefix="ffmpeg-"))
    try:
        print(f"INFO: apt has no ffmpeg, downloading {url}")
        archive = tmp / "ffmpeg.tar.xz"
        download(url, archive)
        with tarfile.open(archive, "r:xz") as tar:
            for m in tar.getmembers():
                name = Path(m.name).name
                if m.isfile() and name in ("ffmpeg", "ffprobe"):
                    m.name = name
                    tar.extract(m, SYSTEM_BIN)
                    (SYSTEM_BIN / name).chmod(0o755)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def required_go_version():
    required = GO_MIN_VERSION
    try:
        m = re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", (AMD_DIR / "go.mod").read_text(), re.MULTILINE)
        if m:
            required = max(required, parse_version(m.group(1)))
    except OSError:
        pass
    return required

def installed_go_version():
    go_bin = shutil.which("go") or str(GO_ROOT / "bin" / "go")
    try:
        out = run([go_bin, "version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_version(out.replace("go version go", ""))

def latest_go_release():
    text = fetch_text(MANIFEST["go_version_url"])
    return text.splitlines()[0].strip() if text else None


def install_go():
    if not ARCH:
        raise RuntimeError(f"Unsupported platform: {platform.machine()}")
    latest = latest_go_release()
    if not latest:
        raise RuntimeError("Could not determine the latest Go version")
    url = MANIFEST["go_download_url"].format(version=latest, arch=ARCH)
    archive = Path(tempfile.gettempdir()) / "go-update.tar.gz"
    try:
        print(f"INFO: Downloading {url}")
        download(url, archive)
        verify_sha256(archive, go_expected_sha(f"{latest}.linux-{ARCH}.tar.gz"), "Go")
        staging = Path(tempfile.mkdtemp(prefix="go-new-", dir=GO_ROOT.parent))
        try:
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(staging)
            if not (staging / "go" / "bin" / "go").exists():
                raise RuntimeError("downloaded archive has no go/bin/go")
            shutil.rmtree(GO_ROOT, ignore_errors=True)
            (staging / "go").rename(GO_ROOT)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        print(f"INFO: Installed {latest}")
    finally:
        archive.unlink(missing_ok=True)

def install_gpac():
    apt, env = _apt()
    has_pkg = run(["apt-cache", "show", "gpac"], env=env,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if has_pkg:
        r = run([*apt, "install", "gpac"], env=env)
        if r.returncode == 0 and shutil.which("MP4Box"):
            print("INFO: GPAC installed from apt")
            return
    ref = MANIFEST["gpac_ver"]
    print(f"INFO: Building GPAC {ref} from source (this takes a while)")
    run([*apt, "install", "build-essential", "pkg-config", "git", "zlib1g-dev"], check=True, env=env)
    build_dir = tempfile.mkdtemp(prefix="gpac-build-")
    try:
        src = os.path.join(build_dir, "gpac")
        run(["git", "clone", "--depth", "1", "--branch", ref, MANIFEST["gpac_repo"], src], check=True, env=env)
        run(["./configure", "--static-bin"], cwd=src, check=True)
        run(["make", f"-j{os.cpu_count() or 1}"], cwd=src, check=True)
        run(["make", "install"], cwd=src, check=True)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)
    if not shutil.which("MP4Box"):
        raise RuntimeError("GPAC was built but MP4Box is not on PATH")

def _extract_zip(url, target, label, sha256=None):
    """Download a zip into target; target is removed again if anything fails."""
    zip_path = PROJECT_DIR / f"{label}.zip"
    try:
        print(f"INFO: Downloading {label} from {url}")
        download(url, zip_path, timeout=180)
        verify_sha256(zip_path, sha256, label)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(target)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        zip_path.unlink(missing_ok=True)

def install_bento4():
    shutil.rmtree(BENTO4_DIR, ignore_errors=True)
    _extract_zip(MANIFEST["bento4_url"], BENTO4_DIR, "bento4", MANIFEST.get("bento4_sha256"))
    bin_dir = bento4_bin_dir()
    if not bin_dir:
        raise RuntimeError("Bento4 archive has no bin directory")
    for exe in bin_dir.iterdir():
        if not exe.is_file():
            continue
        exe.chmod(exe.stat().st_mode | 0o755)
        link = SYSTEM_BIN / exe.name
        if link.is_symlink():
            link.unlink()
        if not link.exists():
            link.symlink_to(exe.resolve())
    print("INFO: Bento4 installed and linked into /usr/local/bin")

def wrapper_url():
    return MANIFEST["wrapper_url_arm64"] if ARCH == "arm64" else MANIFEST["wrapper_url"]

def _remote_meta(url):
    try:
        req = urllib.request.Request(url, headers=USER_AGENT, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return {k: resp.headers.get(k) for k in ("ETag", "Last-Modified", "Content-Length")}
    except Exception:
        return None

def install_wrapper():
    meta = _remote_meta(wrapper_url())
    shutil.rmtree(WRAPPER_DIR, ignore_errors=True)
    _extract_zip(wrapper_url(), WRAPPER_DIR, "wrapper", github_asset_sha(wrapper_url()))
    binary = WRAPPER_DIR / "wrapper"
    if binary.exists():
        binary.chmod(binary.stat().st_mode | 0o755)
    else:
        print("WARN: Wrapper binary not found after extraction")
    if meta:
        (WRAPPER_DIR / ".meta.json").write_text(json.dumps(meta))

def amd_build_stamp():
    rev = run(["git", "-C", str(AMD_DIR), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    go_bin = shutil.which("go") or str(GO_ROOT / "bin" / "go")
    try:
        version = run([go_bin, "version"], capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        version = ""
    return f"{rev}|{version}"

def build_downloader(only_if_stale=False):
    stamp = amd_build_stamp()
    if only_if_stale and AMD_BINARY.exists():
        try:
            if AMD_BUILD_FILE.read_text().strip() == stamp:
                return
        except OSError:
            pass
    go_bin = shutil.which("go") or str(GO_ROOT / "bin" / "go")
    print("INFO: Building the downloader (go build)")
    run([go_bin, "build", "-o", str(AMD_BINARY), "main.go"], cwd=AMD_DIR, check=True)
    AMD_BINARY.chmod(0o755)
    AMD_BUILD_FILE.write_text(stamp)

def install_downloader():
    branch = MANIFEST["amd_branch"]
    if not AMD_DIR.exists():
        print("INFO: Cloning the downloader")
        run(["git", "clone", "--branch", branch, MANIFEST["amd_repo"], str(AMD_DIR)], check=True)
    else:
        git = ["git", "-C", str(AMD_DIR)]
        run([*git, "fetch", "origin", branch], check=True, timeout=120)
        run([*git, "checkout", "-B", branch, f"origin/{branch}", "--force"], check=True, timeout=60)
        run([*git, "reset", "--hard", f"origin/{branch}"], check=True, timeout=60)
    prepare_user_data()
    build_downloader()

@dataclass
class Component:
    key: str
    label: str
    status: str
    detail: str
    apply: Optional[Callable[[], None]] = None

    @property
    def blocking(self):
        return self.status in (STATUS_MISSING, STATUS_OUTDATED)

def _missing_system_parts():
    missing = [b for b in ("git", "wget", "ffmpeg", "ffprobe") if not shutil.which(b)]
    missing += [m for m in ("flask", "yaml") if importlib.util.find_spec(m) is None]
    return missing

def _scan_go(online):
    required, installed = required_go_version(), installed_go_version()
    if installed is None:
        return Component("go", "Go", STATUS_MISSING, f"not installed (need >= {fmt(required)})", install_go)
    if installed < required:
        return Component("go", "Go", STATUS_OUTDATED, f"{fmt(installed)} installed, need >= {fmt(required)}", install_go)
    if online:
        latest = latest_go_release()
        if latest and parse_version(latest) and parse_version(latest) > installed:
            return Component("go", "Go", STATUS_NEWER, f"{fmt(installed)} -> {fmt(parse_version(latest))}", install_go)
    return Component("go", "Go", STATUS_OK, fmt(installed))

def _scan_gpac():
    if shutil.which("MP4Box"):
        return Component("gpac", "GPAC (MP4Box)", STATUS_OK, "installed")
    return Component("gpac", "GPAC (MP4Box)", STATUS_MISSING, "MP4Box not found", install_gpac)

def _bento_version(text):
    m = re.search(r"SDK-(\d+(?:-\d+)+)", text or "")
    return m.group(1) if m else None

def _scan_bento4():
    bin_dir = bento4_bin_dir()
    if not bin_dir or not (bin_dir / "mp4decrypt").exists():
        return Component("bento4", "Bento4", STATUS_MISSING, "not installed", install_bento4)
    installed = _bento_version(bin_dir.parent.name)
    pinned = _bento_version(MANIFEST["bento4_url"])
    if installed and pinned and installed != pinned:
        return Component("bento4", "Bento4", STATUS_NEWER, f"{installed} -> {pinned} (Manifest)", install_bento4)
    return Component("bento4", "Bento4", STATUS_OK, installed or "installed")

def _scan_wrapper(online):
    if not (WRAPPER_DIR / "wrapper").exists():
        return Component("wrapper", "Wrapper", STATUS_MISSING, "not installed", install_wrapper)
    if online:
        try:
            saved = json.loads((WRAPPER_DIR / ".meta.json").read_text())
        except (OSError, ValueError):
            saved = None
        remote = _remote_meta(wrapper_url())
        if saved and remote and (saved.get("ETag"), saved.get("Last-Modified")) != (remote.get("ETag"), remote.get("Last-Modified")):
            return Component("wrapper", "Wrapper", STATUS_NEWER, "new release available", install_wrapper)
    return Component("wrapper", "Wrapper", STATUS_OK, "installed")

def _scan_downloader(online):
    branch = MANIFEST["amd_branch"]
    if not (AMD_DIR / "main.go").exists():
        return Component("amd", "Downloader", STATUS_MISSING, "not cloned", install_downloader)
    git = ["git", "-C", str(AMD_DIR)]
    current = run([*git, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
    if current != branch:
        return Component("amd", "Downloader", STATUS_NEWER, f"on '{current}', Manifest wants '{branch}'", install_downloader)
    if online and run([*git, "fetch", "origin", branch], capture_output=True, timeout=60).returncode == 0:
        behind = run([*git, "rev-list", "--count", f"HEAD..origin/{branch}"], capture_output=True, text=True).stdout.strip()
        if behind.isdigit() and int(behind) > 0:
            return Component("amd", "Downloader", STATUS_NEWER, f"{behind} new commit(s) on {branch}", install_downloader)
    return Component("amd", "Downloader", STATUS_OK, f"branch {branch}")

def _scan_amd_build():
    if not (AMD_DIR / "main.go").exists():
        return Component("amd-build", "Downloader build", STATUS_OK, "waits for the downloader")
    try:
        fresh = AMD_BINARY.exists() and AMD_BUILD_FILE.read_text().strip() == amd_build_stamp()
    except OSError:
        fresh = False
    if fresh:
        return Component("amd-build", "Downloader build", STATUS_OK, "built")
    return Component("amd-build", "Downloader build", STATUS_NEWER, "binary missing or out of date (go run is used meanwhile)",
                     lambda: build_downloader(only_if_stale=True))

def scan(online=True):
    """Inspect every component and return a list of Component objects."""
    parts = _missing_system_parts()
    system = (Component("system", "System packages", STATUS_MISSING, "missing: " + ", ".join(parts), install_system_packages)
              if parts else Component("system", "System packages", STATUS_OK, "installed"))
    return [system, _scan_go(online), _scan_gpac(), _scan_bento4(), _scan_wrapper(online), _scan_downloader(online), _scan_amd_build(), _scan_rip()]

def check():
    """Offline check used by Main.py; returns the components that block startup."""
    setup_path()
    return [c for c in scan(online=False) if c.blocking]

def upstream_hints():
    """Notes about newer upstream versions that need a manual Manifest.ini edit."""
    hints = []
    tags = remote_tags("https://github.com/axiomatic-systems/Bento4.git")
    builds = [t for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+-\d+", t)]
    pinned = _bento_version(MANIFEST["bento4_url"])
    if builds and pinned:
        key = lambda s: tuple(int(x) for x in re.findall(r"\d+", s))
        latest = max(builds, key=key)
        if key(latest) > key(pinned):
            hints.append(f"Bento4 {latest} exists upstream, Manifest pins {pinned}")
    gpac = [t for t in remote_tags(MANIFEST["gpac_repo"]) if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    if gpac:
        latest = max(gpac, key=lambda s: parse_version(s))
        if parse_version(latest) > (parse_version(MANIFEST["gpac_ver"]) or (0,)):
            hints.append(f"GPAC {latest} exists upstream, Manifest pins {MANIFEST['gpac_ver']}")
    return hints

def cmd_check():
    problems = check()
    if not problems:
        print("Everything is in place.")
        return 0
    for c in problems:
        print(f"  - {c.label}: {c.detail}")
    print("\nRun 'rip update' to fix this.")
    return 1

def cmd_update(assume_yes=False):
    setup_path()
    print("Scanning components...\n")
    components = scan(online=True)
    todo = [c for c in components if c.status != STATUS_OK]

    for c in components:
        mark = {"ok": "OK      ", "missing": "MISSING ", "outdated": "OUTDATED", "newer": "UPDATE  "}[c.status]
        print(f"  [{mark}] {c.label}: {c.detail}")
    for hint in upstream_hints():
        print(f"  [NOTE    ] {hint}")

    if not todo:
        prepare_user_data()
        print("\nEverything is up to date.")
        return 0
    if not is_root():
        print("\nUpdating needs root. Run: sudo rip update")
        return 1

    print(f"\n{len(todo)} item(s) to install or update: " + ", ".join(c.label for c in todo))
    if not assume_yes:
        try:
            answer = input("Update now? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Nothing changed.")
            return 0

    failed = []
    for c in todo:
        print(f"\n== {c.label} ==")
        try:
            c.apply()
            setup_path()
        except Exception as e:
            print(f"ERROR: {c.label} failed: {e}")
            failed.append(c.label)
    prepare_user_data()

    if failed:
        print("\nFailed: " + ", ".join(failed))
        return 1
    print("\nDone.")
    return 0

def main(argv):
    command = argv[0] if argv else "update"
    if command in ("update", "install"):
        return cmd_update(assume_yes=any(a in ("-y", "--yes") for a in argv[1:]))
    if command == "check":
        return cmd_check()
    print("Usage: Start.py [update [-y] | check]")
    return 2
def install_rip():
    RIP_SCRIPT.chmod(RIP_SCRIPT.stat().st_mode | 0o755)
    link = SYSTEM_BIN / "rip"
    if link.is_symlink():
        link.unlink()
    link.symlink_to(RIP_SCRIPT)
    print("INFO: 'rip' command linked into /usr/local/bin")

def _scan_rip():
    link = SYSTEM_BIN / "rip"
    if link.is_symlink():
        if link.exists() and link.resolve() == RIP_SCRIPT.resolve():
            return Component("rip", "rip command", STATUS_OK, "linked")
        return Component("rip", "rip command", STATUS_NEWER, "link is broken or points elsewhere", install_rip)
    if link.exists():
        return Component("rip", "rip command", STATUS_OK, "/usr/local/bin/rip is a regular file, left alone")
    return Component("rip", "rip command", STATUS_NEWER, "not linked", install_rip)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
