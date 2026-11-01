import configparser
import os
import platform
import re
import tarfile
import subprocess
import urllib.request
import zipfile
import sys
import tempfile
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
BENTO4_DIR = PROJECT_DIR / "bento4"
WRAPPER_DIR = PROJECT_DIR / "wrapper"
AMD_DIR = PROJECT_DIR / "apple-music-downloader"
GO_ROOT = Path("/usr/local/go")
MANIFEST_FILE = PROJECT_DIR / "App" / "Manifest.ini"
MANIFEST_SECTION = "manifest"

# Fallback values, used when Manifest.ini is gone
_DEFAULTS = {
    "go_min_version": "1.23.1",
    "gpac_ver": "v2.4.0",
    "amd_branch": "v1",
    "bento4_url": "https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-641.x86_64-unknown-linux.zip",
    "wrapper_url": "https://github.com/WorldObservationLog/wrapper/releases/download/wrapper.x86_64.latest/Wrapper.x86_64.latest.zip",
    "ffmpeg_static_url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-{arch}-static.tar.xz",
}

def load_manifest():
    """Reads Manifest.ini and returns a dict (defaults overridden by the file)."""
    values = dict(_DEFAULTS)
    if not MANIFEST_FILE.exists():
        print(f"WARN: {MANIFEST_FILE.name} not found, using built-in defaults")
        return values
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(MANIFEST_FILE)
    except configparser.Error as e:
        print(f"WARN: Could not parse {MANIFEST_FILE.name}: {e}. Using built-in defaults")
        return values
    if not cp.has_section(MANIFEST_SECTION):
        print(f"WARN: [{MANIFEST_SECTION}] section missing in {MANIFEST_FILE.name}, using built-in defaults")
        return values
    for key, val in cp[MANIFEST_SECTION].items():
        if key in values and val.strip():
            values[key] = val.strip()
    return values

MANIFEST = load_manifest()

GPAC_VER = MANIFEST["gpac_ver"]
AMD_BRANCH = MANIFEST["amd_branch"]
BENTO4_URL = MANIFEST["bento4_url"]
WRAPPER_URL = MANIFEST["wrapper_url"]
FFMPEG_STATIC_URL = MANIFEST["ffmpeg_static_url"]
try:
    GO_MIN_VERSION = tuple(int(x) for x in MANIFEST["go_min_version"].split("."))
except ValueError:
    print(f"WARN: Bad go_min_version '{MANIFEST['go_min_version']}' in Manifest, using default")
    GO_MIN_VERSION = tuple(int(x) for x in _DEFAULTS["go_min_version"].split("."))

#Step: 1 Installation Segment
#Task: 0 ffmpeg installation (apt first, static build as fallback)
def ensure_ffmpeg():
    """Installs ffmpeg/ffprobe if missing."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        print("INFO: ffmpeg OK")
        return True
    if os.geteuid() != 0:
        print("ERROR: ffmpeg is missing and root is required to install it")
        return False

    print("INFO: ffmpeg missing, installing from apt...")
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    subprocess.run(["apt-get", "-y", "update"], env=env)
    subprocess.run(["apt-get", "-y", "install", "ffmpeg"], env=env)
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        print("INFO: ffmpeg installed from apt")
        return True

    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if not arch:
        print(f"WARN: No static ffmpeg build for {platform.machine()}")
        return False
    url = FFMPEG_STATIC_URL.format(arch=arch)
    tmp = Path(tempfile.mkdtemp(prefix="ffmpeg-"))
    try:
        print(f"INFO: apt failed, downloading {url}...")
        archive = tmp / "ffmpeg.tar.xz"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(archive, "wb") as out:
            shutil.copyfileobj(resp, out)
        with tarfile.open(archive, "r:xz") as tar:
            for m in tar.getmembers():
                name = Path(m.name).name
                if m.isfile() and name in ("ffmpeg", "ffprobe"):
                    m.name = name
                    tar.extract(m, "/usr/local/bin")
                    (Path("/usr/local/bin") / name).chmod(0o755)
        ok = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        print("INFO: static ffmpeg installed" if ok else "WARN: static ffmpeg install incomplete")
        return ok
    except Exception as e:
        print(f"WARN: Static ffmpeg install failed: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

#Task: 1 Go go Power Rangers
def _parse_go_version(text):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None

def _installed_go_version():
    go_bin = shutil.which("go") or str(GO_ROOT / "bin" / "go")
    try:
        out = subprocess.run([go_bin, "version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return _parse_go_version(out.replace("go version go", ""))

def _required_go_version():
    required = GO_MIN_VERSION
    gomod = PROJECT_DIR / "apple-music-downloader" / "go.mod"
    try:
        m = re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", gomod.read_text(), re.MULTILINE)
        if m:
            required = max(required, _parse_go_version(m.group(1)))
    except OSError:
        pass
    return required

def ensure_go():
    """Checking Go version and updateing if needed."""
    os.environ["PATH"] = f"{GO_ROOT / 'bin'}:{os.environ['PATH']}"

    required = _required_go_version()
    installed = _installed_go_version()
    req_str = ".".join(map(str, required))

    if installed and installed >= required:
        print(f"INFO: Go {'.'.join(map(str, installed))} OK (Required >= {req_str})")
        return True

    inst_str = ".".join(map(str, installed)) if installed else "brak"
    print(f"INFO: Go {inst_str} jest za stare (Required >= {req_str}), Updateing...")
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if not arch:
        print(f"WARN: Wrong platform: {platform.machine()}")
        return False

    tmp = Path("/tmp/go-update.tar.gz")
    try:
        with urllib.request.urlopen("https://go.dev/VERSION?m=text", timeout=30) as r:
            latest = r.read().decode().splitlines()[0].strip()
        url = f"https://go.dev/dl/{latest}.linux-{arch}.tar.gz"
        print(f"Download {url}...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
        staging = Path(tempfile.mkdtemp(prefix="go-new-", dir=GO_ROOT.parent))
        try:
            with tarfile.open(tmp, "r:gz") as tar:
                tar.extractall(staging)
            if not (staging / "go" / "bin" / "go").exists():
                raise RuntimeError("downloaded archive has no go/bin/go")
            shutil.rmtree(GO_ROOT, ignore_errors=True)
            (staging / "go").rename(GO_ROOT)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        print(f"INFO: Updated {latest}")
        return True
    except Exception as e:
        print(f"WARN: Update didnt come throu: {e}")
        return False
    finally:
        if tmp.exists():
            tmp.unlink()

#Task: 2 AMD download
def ensure_downloader_compat():
    """Keeps the downloader on a branch compatible with the old wrapper and fills empty wrapper ports."""
    if not AMD_DIR.exists():
        return
    try:
        cur = subprocess.run(
            ["git", "-C", str(AMD_DIR), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        if cur != AMD_BRANCH:
            print(f"INFO: Downloader on branch '{cur}', switching to '{AMD_BRANCH}'...")
            subprocess.run(["git", "-C", str(AMD_DIR), "fetch", "origin", AMD_BRANCH], check=True, timeout=120)
            subprocess.run(["git", "-C", str(AMD_DIR), "checkout", "-B", AMD_BRANCH, f"origin/{AMD_BRANCH}"], check=True, timeout=60)
        else:
            print(f"INFO: Downloader on branch {AMD_BRANCH} OK")
    except Exception as e:
        print(f"WARN: Could not check downloader branch: {e}")

    cfg = AMD_DIR / "config.yaml"
    try:
        if cfg.exists():
            text = cfg.read_text()
            new = re.sub(r"^decrypt-m3u8-port:[ \t]*(''|\"\")?[ \t]*$", 'decrypt-m3u8-port: "127.0.0.1:10020"', text, flags=re.MULTILINE)
            new = re.sub(r"^get-m3u8-port:[ \t]*(''|\"\")?[ \t]*$", 'get-m3u8-port: "127.0.0.1:20020"', new, flags=re.MULTILINE)
            if new != text:
                cfg.write_text(new)
                print("INFO: Filled empty wrapper ports in config.yaml")
    except OSError as e:
        print(f"WARN: Could not modify config.yaml: {e}")

#Task: 3 Gpac installation
def install_gpac(apt, env):
    """Installing GPAC for MP4Box"""
    if shutil.which("MP4Box"):
        print("MP4Box is Installed <3")
        return
    has_pkg = subprocess.run(
        ["apt-cache", "show", "gpac"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0

    if has_pkg:
        r = subprocess.run([*apt, "install", "gpac"], env=env)
        if r.returncode == 0 and shutil.which("MP4Box"):
            print("GPAC Installed from APT.")
            return

    print(f"GPAC is unavailable from APT.\nInstalling from source\n{GPAC_VER}\n")
    subprocess.run(
        [*apt, "install", "build-essential", "pkg-config", "git", "zlib1g-dev"],
        check=True, env=env,
    )

    build_dir = tempfile.mkdtemp(prefix="gpac-build-")
    try:
        src = os.path.join(build_dir, "gpac")
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", GPAC_VER,
            "https://github.com/gpac/gpac.git", src],
            check=True, env=env,
        )
        subprocess.run(["./configure", "--static-bin"], cwd=src, check=True)
        subprocess.run(["make", f"-j{os.cpu_count() or 1}"], cwd=src, check=True)
        subprocess.run(["make", "install"], cwd=src, check=True)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)
    if not shutil.which("MP4Box"):
        raise RuntimeError("GPAC is built but MP4Box is not in the PATH.")
    print("GPAC is Ready")


def firstsetup():
    if os.geteuid() != 0:
        print("ERROR: This script must be run as root. Exiting...")
        sys.exit(1)

    try:

        #Task: 3 Install rest of packages
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        apt = ["apt-get", "-y", "-o", "Acquire::Retries=3", "-o", "Dpkg::Lock::Timeout=60"]

        subprocess.run([*apt, "update"], check=True, env=env)
        subprocess.run(
            [*apt, "install", "git", "ffmpeg", "wget",
             "python3-flask", "python3-yaml"],
            check=True,
            env=env,
        )

        if not ensure_go():
            raise RuntimeError("Couldn't install Go")

        install_gpac(apt, env)

        print("Packages installed successfully.")

        #Task: 4 Download and set up Bento4
        zip_path = PROJECT_DIR / "bento4.zip"

        if not BENTO4_DIR.exists():
            try:
                print(f"Downloading Bento4 from {BENTO4_URL}...")
                req = urllib.request.Request(
                    BENTO4_URL,
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
                )
                with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out:
                    shutil.copyfileobj(resp, out)

                print("Extracting Bento4...")
                BENTO4_DIR.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(BENTO4_DIR)

                print("Bento4 installed inside project folder.")
            except Exception:
                shutil.rmtree(BENTO4_DIR, ignore_errors=True)
                raise
            finally:
                if zip_path.exists():
                    os.remove(zip_path)

            #Taask: 6 Symbolic links to Bento4 tools in /usr/local/bin
            bin_candidates = list(BENTO4_DIR.glob("Bento4*"))
            if bin_candidates:
                bin_dir = bin_candidates[0] / "bin"
                print(f"DEBUG: Creating symbolic links for Bento4 tools from: {bin_dir}")
                print(f"DEBUG: Bin directory exists: {bin_dir.exists()}")

                if not bin_dir.exists():
                    raise RuntimeError(f"Bento4 bin directory does not exist: {bin_dir}")
                    
                all_files = list(bin_dir.glob("*"))
                print(f"DEBUG: All files in bin: {[f.name for f in all_files]}")
                print("Setting execute permissions on all Bento4 tools...")
                for exe_file in all_files:
                    if exe_file.is_file():
                        try:
                            current_mode = exe_file.stat().st_mode
                            new_mode = current_mode | 0o755  # rwxr-xr-x
                            exe_file.chmod(new_mode)
                            print(f"  CHMOD: Set execute permission on {exe_file.name}")
                        except Exception as e:
                            print(f"  ERROR: Failed to set execute permission on {exe_file.name}: {e}")

                # Now check for executable files again
                executable_files = [f for f in all_files if f.is_file() and os.access(f, os.X_OK)]
                print(f"DEBUG: Executable files after chmod: {[f.name for f in executable_files]}")

               
                os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

                # Create symbolic links with detailed error reporting
                success_count = 0
                error_count = 0

                for exe_file in executable_files:
                    try:
                        link_path = Path("/usr/local/bin") / exe_file.name
                        print(f"DEBUG: Attempting to create symlink: {exe_file.name}")
                        print(f"DEBUG: Source: {exe_file.absolute()}")
                        print(f"DEBUG: Target: {link_path}")

                        if link_path.exists():
                            print(f"  INFO: Already exists: {exe_file.name}")
                        else:
                            os.symlink(str(exe_file.absolute()), str(link_path))
                            print(f"  SUCCESS: Created symlink for {exe_file.name}")
                            success_count += 1

                    except Exception as e:
                        print(f"  ERROR: Failed to create symlink for {exe_file.name}: {e}")
                        error_count += 1

                print(f"SUMMARY: {success_count} symlinks created, {error_count} errors")

                # Verify what actually got created
                print("Verifying /usr/local/bin contents...")
                usr_local_bin = Path("/usr/local/bin")
                if usr_local_bin.exists():
                    bento4_links = [f for f in usr_local_bin.glob("*") if f.is_symlink()]
                    print(f"Found {len(bento4_links)} symlinks in /usr/local/bin")
                    for link in bento4_links:
                        if any(exe.name == link.name for exe in executable_files):
                            print(f"  VERIFIED: {link.name} -> {link.readlink()}")
                else:
                    print("ERROR: /usr/local/bin does not exist")
            else:
                print("WARN: Could not find Bento4 extracted folder")

        else:
            print("INFO: Bento4 already exists, skipping download")

            # Ensure Bento4 tools are available even if already downloaded
            bin_candidates = list(BENTO4_DIR.glob("Bento4*"))
            if bin_candidates:
                bin_dir = bin_candidates[0] / "bin"
                os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

                # Check if symbolic links need to be created
                try:
                    missing_links = []
                    for exe_file in bin_dir.glob("*"):
                        if exe_file.is_file() and os.access(exe_file, os.X_OK):
                            link_path = Path("/usr/local/bin") / exe_file.name
                            if not link_path.exists():
                                missing_links.append((exe_file, link_path))

                    if missing_links:
                        print("Creating missing Bento4 symbolic links...")
                        for exe_file, link_path in missing_links:
                            os.symlink(exe_file, link_path)
                            print(f"  Created symlink: {exe_file.name}")
                    else:
                        print("Bento4 tools already available system-wide")

                except Exception as e:
                    print(f"WARN: Could not verify/create symbolic links: {e}")
                    print(f"Added existing Bento4 bin to current session PATH: {bin_dir}")

        # Step 3: Download and extract wrapper
        wrapper_zip = PROJECT_DIR / "wrapper.x86_64.zip"

        if not WRAPPER_DIR.exists():
            print(f"Downloading wrapper from {WRAPPER_URL}...")
            req = urllib.request.Request(WRAPPER_URL, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp, open(wrapper_zip, "wb") as out:
                    shutil.copyfileobj(resp, out)
                print("Extracting wrapper...")
                WRAPPER_DIR.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(wrapper_zip, "r") as zip_ref:
                    zip_ref.extractall(WRAPPER_DIR)
            except Exception:
                shutil.rmtree(WRAPPER_DIR, ignore_errors=True)
                raise
            finally:
                if wrapper_zip.exists():
                    os.remove(wrapper_zip)

            # Ensure the wrapper binary is executable
            wrapper_bin = WRAPPER_DIR / "wrapper"
            try:
                if wrapper_bin.exists():
                    current_mode = wrapper_bin.stat().st_mode
                    wrapper_bin.chmod(current_mode | 0o755)
                    print("Set execute permission on wrapper binary")
                else:
                    print("WARN: Wrapper binary not found after extraction")
            except Exception as e:
                print(f"WARN: Failed to chmod wrapper binary: {e}")

            print("Wrapper extracted inside project folder")
        else:
            print("INFO: Wrapper already exists, skipping download")

        # Step 4: Clone AMD repo
        if not AMD_DIR.exists():
            print("Cloning Apple Music Downloader...")
            subprocess.run(
                ["git", "clone", "--branch", AMD_BRANCH, "https://github.com/zhaarey/apple-music-downloader", str(AMD_DIR)],
                check=True
            )
            print("Apple Music Downloader cloned inside project folder")
        else:
            print("INFO: Apple Music Downloader already exists, skipping clone")

        print("First setup complete!")

    except (subprocess.CalledProcessError, RuntimeError, OSError) as e:
        print(f"ERROR: Failed during setup: {e}")
        sys.exit(1)

def start():
    print("Starting Apple Music Downloader Web UI...")

    # Ensure Bento4 and Wrapper are in PATH locally
    bin_candidates = list(BENTO4_DIR.glob("Bento4*"))
    if bin_candidates:
        bin_dir = bin_candidates[0] / "bin"
        os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

    os.environ["PATH"] = f"{WRAPPER_DIR}:{os.environ['PATH']}"

    if not ensure_ffmpeg():
        print("ERROR: ffmpeg is required. Exiting...")
        sys.exit(1)
    ensure_go()
    ensure_downloader_compat()

    # Import and run the Flask app (app.py may live in the project root or in App/)
    for d in (PROJECT_DIR, PROJECT_DIR / "App"):
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    try:
        from app import app
    except ImportError as e:
        print(f"ERROR: Could not import the web UI (app.py): {e}")
        print(f"       Put app.py in {PROJECT_DIR} or {PROJECT_DIR / 'App'}")
        sys.exit(1)

    # Default keeps LAN access (LXC); set REAPPER_HOST=127.0.0.1 to restrict
    host = os.environ.get("REAPPER_HOST", "0.0.0.0")
    port = int(os.environ.get("REAPPER_PORT", "5000"))
    app.run(host=host, port=port, debug=False)

def main():
    # First run check
    marker_file = PROJECT_DIR / "firstrun"
    if not marker_file.exists():
        firstsetup()
        with open(marker_file, "w") as f:
            f.write("This file marks that first setup has been completed.\n")
    start()


if __name__ == "__main__":
    main()
