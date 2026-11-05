import subprocess
import threading
import time
import signal
import shlex
import yaml
import os
import json
import base64
import re
from urllib.parse import urlparse
from flask import Response
from .Launcher import Start
from flask import render_template, request, jsonify
from . import app

wrapper_process = None
wrapper_running = False
wrapper_needs_2fa = False
download_process = None
download_running = False
download_paused = False
last_download = None
LOG_LIMIT = 500
wrapper_logs = []
downloader_logs = []
log_lock = threading.Lock()
auto_state_lock = threading.Lock()
AUTO_LOGIN_TRIES = 3
AUTO_LOGIN_BASE_LOCK = 300
AUTO_LOGIN_WINDOW = 3600
AUTO_LOGIN_MAX_LOCK = 86400
AUTO_LOGIN_RETRY_DELAY = 10
wrapper_stop_requested = False
download_lock = threading.Lock()
file_sink = None
DEFAULT_PREFS = {"special_audio": True, "format": "ATMOS", "select_all": False, "theme": "dark", "language": "en", "advanced_settings": False}
PROJECT_DIR = str(Start.PROJECT_DIR)
USER_DIR = str(Start.USER_DIR)
AMD_DIR = str(Start.AMD_DIR)
WRAPPER_DIR = str(Start.WRAPPER_DIR)
CONFIG_PATH = str(Start.CONFIG_FILE)
AUTH_ERROR_PATTERNS = [
    (re.compile(r"(wrong|invalid|incorrect).*(2fa|verification|code)|(2fa|verification).*(wrong|invalid|incorrect|fail)", re.I),
     "Error 10 - wrong 2FA"),
    (re.compile(r"(wrong|invalid|incorrect).*(password|credentials)|authentication failed|bad credentials", re.I),
     "Error 11 - wrong email or password"),
]

def set_file_sink(sink):
    global file_sink
    file_sink = sink

def file_log(source, line):
    if file_sink is not None:
        file_sink.write(f"[{source}] {line}\n")

def add_log(target, line):
    with log_lock:
        target.append(line)
        if len(target) > LOG_LIMIT:
            del target[:len(target) - LOG_LIMIT]

def fresh_auto_state():
    return {"failures": 0, "level": 0, "last_lockout": 0.0, "locked_until": 0.0}

def load_auto_state():
    state = fresh_auto_state()
    try:
        with open(Start.AUTO_LOGIN_FILE, "r") as f:
            data = json.load(f)
        for key in state:
            if isinstance(data.get(key), (int, float)):
                state[key] = data[key]
    except (OSError, ValueError, AttributeError):
        pass
    return state

def save_auto_state(state):
    try:
        os.makedirs(USER_DIR, exist_ok=True)
        with open(Start.AUTO_LOGIN_FILE, "w") as f:
            json.dump(state, f)
    except OSError:
        pass

def auto_login_lock_remaining():
    with auto_state_lock:
        return max(0, int(load_auto_state()["locked_until"] - time.time()))

def register_auto_login_success():
    with auto_state_lock:
        save_auto_state(fresh_auto_state())

def register_auto_login_failure():
    with auto_state_lock:
        state = load_auto_state()
        now = time.time()
        state["failures"] += 1
        if state["failures"] < AUTO_LOGIN_TRIES:
            save_auto_state(state)
            return 0
        within_window = state["last_lockout"] and now - state["last_lockout"] < AUTO_LOGIN_WINDOW
        state["level"] = state["level"] + 1 if within_window else 0
        seconds = min(AUTO_LOGIN_BASE_LOCK * 2 ** state["level"], AUTO_LOGIN_MAX_LOCK)
        state["failures"] = 0
        state["last_lockout"] = now
        state["locked_until"] = now + seconds
        save_auto_state(state)
        return seconds

def format_wait(seconds):
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes} min {rest} s" if minutes and rest else (f"{minutes} min" if minutes else f"{rest} s")

def schedule_auto_login_retry():
    timer = threading.Timer(AUTO_LOGIN_RETRY_DELAY, attempt_auto_login)
    timer.daemon = True
    timer.start()

def amd_state():
    if not os.path.exists(os.path.join(str(AMD_DIR), "main.go")):
        return "missing"
    if download_running:
        return "paused" if download_paused else "downloading"
    return "ready"

def amd_command(*args):
    binary = str(Start.AMD_BINARY)
    base = [binary] if os.access(binary, os.X_OK) else ["go", "run", "main.go"]
    return [*base, *args]

def is_apple_music_url(link):
    try:
        parts = urlparse(link)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    return parts.scheme == "https" and (host == "music.apple.com" or host.endswith(".music.apple.com"))

@app.before_request
def csrf_guard():
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return jsonify({"status": "error", "msg": "Bad origin"}), 403
            
def stream_wrapper_logs(proc, target_list, email=None, password=None, auto_login=False):
    """Thread target to read logs from wrapper process and store them."""
    global wrapper_running, wrapper_needs_2fa
    login_successful = False
    auth_error = None
    pipe = proc.stdout

    try:
        for line in iter(pipe.readline, ''):
            line = line.strip()
            if not line:
                continue

            if password and password in line:
                line = line.replace(password, "********")

            add_log(target_list, line)
            file_log("WRAPPER LOG", line)

            if "credentialHandler:" in line and "2FA: true" in line:
                wrapper_needs_2fa = True
                add_log(target_list, "2FA required - please enter your code")

            err = detect_auth_error(line)
            if err and not auth_error:
                auth_error = err
                add_log(target_list, err)

            if "response type 6" in line or "account info cached successfully" in line:
                register_auto_login_success()
                wrapper_running = True
                wrapper_needs_2fa = False
                login_successful = True
                if auto_login:
                    add_log(target_list, "Auto-login successful. Ready for downloads.")
                else:
                    add_log(target_list, "Wrapper login successful. Ready for downloads.")
                    if email and password:
                        if save_credentials(email, password):
                            add_log(target_list, "Credentials saved for auto-login")
                        else:
                            add_log(target_list, "Failed to save credentials")
    except Exception as e:
        add_log(target_list, f"Error reading wrapper logs: {str(e)}")
    finally:
        exit_code = proc.wait() 
        if not login_successful:
            add_log(target_list, f"Login failed - wrapper process exited with code: {exit_code}")
            wrapper_running = False
            wrapper_needs_2fa = False
            if auto_login and not wrapper_stop_requested:
                if auth_error:
                    add_log(target_list, "Auto-login rejected by Apple, deleting saved credentials")
                    delete_credentials()
                    register_auto_login_success()
                else:
                    locked_for = register_auto_login_failure()
                    if locked_for:
                        add_log(target_list, f"Auto-login failed {AUTO_LOGIN_TRIES} times, next attempt in {format_wait(locked_for)}")
                    else:
                        add_log(target_list, f"Auto-login failed (no auth error detected), saved credentials kept, retrying in {AUTO_LOGIN_RETRY_DELAY} s")
                        schedule_auto_login_retry()
        elif exit_code != 0:
            add_log(target_list, f"Wrapper process ended unexpectedly with exit code: {exit_code}")
            wrapper_running = False
            wrapper_needs_2fa = False
        else:
            add_log(target_list, "Wrapper process ended normally")
            wrapper_running = False
            wrapper_needs_2fa = False
        pipe.close()

def detect_auth_error(line):
    for pattern, message in AUTH_ERROR_PATTERNS:
        if pattern.search(line):
            return message
    return None

AMD_SELECT_PROMPT = "Please select from the"

def stream_download_logs(proc, target_list, auto_all=False):
    """Thread target to read logs from download process and store them.

    With auto_all=True every AMD selection prompt is answered with "all".
    """
    global download_running, download_paused
    pipe = proc.stdout
    
    try:
        for line in iter(pipe.readline, ''):
            line = line.strip()
            if line:
                add_log(target_list, line)
                file_log("DOWNLOAD LOG", line)
                if auto_all and AMD_SELECT_PROMPT in line:
                    try:
                        proc.stdin.write("all\n")
                        proc.stdin.flush()
                        add_log(target_list, "Auto-selected: all")
                    except (BrokenPipeError, OSError, ValueError) as e:
                        add_log(target_list, f"Could not send 'all' to downloader: {str(e)}")
    except Exception as e:
        add_log(target_list, f"Error reading download logs: {str(e)}")
    finally:
        exit_code = proc.wait()
        if proc is download_process:
            if exit_code == 0:
                add_log(target_list, "Download completed successfully.")
            else:
                add_log(target_list, f"Download failed with exit code: {exit_code}")
            download_running = False
            download_paused = False
        pipe.close()
        if proc.stdin:
            try:
                proc.stdin.close()
            except Exception:
                pass

def signal_download(sig):
    proc = download_process
    if proc is None or proc.poll() is not None:
        return False
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True

def launch_download(cmd, select_all):
    global download_process, download_paused
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE if select_all else None,
        bufsize=1,
        universal_newlines=True,
        cwd=AMD_DIR,
        start_new_session=True
    )
    download_process = process
    download_paused = False
    threading.Thread(target=stream_download_logs, args=(process, downloader_logs, select_all), daemon=True).start()

def get_credentials_path():
    """Get the path to the credentials file"""
    return str(Start.CREDENTIALS_FILE)

def save_credentials(email, password):
    """Save credentials to file (base64 encoded for basic obfuscation)"""
    try:
        credentials = {
            "email": base64.b64encode(email.encode()).decode(),
            "password": base64.b64encode(password.encode()).decode()
        }
        os.makedirs(USER_DIR, exist_ok=True)
        path = get_credentials_path()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(credentials, f)
        os.chmod(path, 0o600)
        return True
    except Exception as e:
        print(f"Error saving credentials: {e}")
        return False

def load_credentials():
    """Load and decode saved credentials"""
    try:
        credentials_path = get_credentials_path()
        if os.path.exists(credentials_path):
            with open(credentials_path, 'r') as f:
                credentials = json.load(f)
            email = base64.b64decode(credentials["email"]).decode()
            password = base64.b64decode(credentials["password"]).decode()
            return email, password
    except Exception as e:
        print(f"Error loading credentials: {e}")
    return None, None

def delete_credentials():
    """Delete saved credentials"""
    try:
        credentials_path = get_credentials_path()
        if os.path.exists(credentials_path):
            os.remove(credentials_path)
        return True
    except Exception as e:
        print(f"Error deleting credentials: {e}")
        return False

def attempt_auto_login():
    """Try to automatically login with saved credentials"""
    email, password = load_credentials()
    if email and password:
        if auto_login_lock_remaining():
            return False
        add_log(wrapper_logs, "Found saved credentials, attempting auto-login...")
        return start_wrapper_login(email, password, auto_login=True)
    return False
    
def start_wrapper_login(email, password, auto_login=False):
    """Start wrapper login process"""
    global wrapper_process, wrapper_running, wrapper_stop_requested
    
    if wrapper_process and wrapper_process.poll() is None:
        if not auto_login:
            add_log(wrapper_logs, "Wrapper already running")
        return False

    if not auto_login:
        with log_lock:
            wrapper_logs.clear()
    
    wrapper_stop_requested = False
    prefix = "Auto-login: " if auto_login else ""
    add_log(wrapper_logs, f"{prefix}Starting wrapper login for {email}...")
    wrapper_dir = WRAPPER_DIR
    wrapper_path = os.path.join(wrapper_dir, "wrapper")
    
    cmd = [wrapper_path, "-L", f"{email}:{password}"]
    add_log(wrapper_logs, f"{prefix}Executing: {wrapper_path} -L {email}:********")
    add_log(wrapper_logs, f"{prefix}Working directory: {wrapper_dir}")
    
    try:
        wrapper_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
            cwd=wrapper_dir 
        )
        
        threading.Thread(target=stream_wrapper_logs, args=(wrapper_process, wrapper_logs, email, password, auto_login), daemon=True).start()
        
        add_log(wrapper_logs, f"{prefix}Wrapper process started, waiting for login confirmation...")
        return True
        
    except Exception as e:
        add_log(wrapper_logs, f"{prefix}Error starting wrapper: {str(e)}")
        return False


@app.route("/")
def index():
    email, password = load_credentials()
    if email and password and not wrapper_running and (not wrapper_process or wrapper_process.poll() is not None):
        threading.Thread(target=attempt_auto_login, daemon=True).start()
    
    prefs = read_prefs()
    return render_template("Home.html", wrapper_running=wrapper_running, has_saved_credentials=email is not None, saved_email=email if email else "", amd_state=amd_state(), theme=prefs["theme"], language=prefs["language"])


@app.route("/login_wrapper", methods=["POST"])
def login_wrapper():
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""

    if not email or not password:
        return jsonify({"status": "error", "msg": "Email and password are required"})

    if wrapper_process and wrapper_process.poll() is None:
        return jsonify({"status": "error", "msg": "Wrapper already running"})

    if start_wrapper_login(email, password, auto_login=False):
        return jsonify({"status": "ok", "msg": "Wrapper process started, waiting for login..."})
    else:
        return jsonify({"status": "error", "msg": "Failed to start wrapper"})

@app.route("/submit_2fa", methods=["POST"])
def submit_2fa():
    global wrapper_process, wrapper_needs_2fa
    
    two_fa_code = request.form.get("twofa_code")
    
    if not wrapper_needs_2fa:
        return jsonify({"status": "error", "msg": "2FA not required"})
    
    if not wrapper_process or wrapper_process.poll() is not None:
        return jsonify({"status": "error", "msg": "Wrapper not running"})
    
    if not two_fa_code:
        return jsonify({"status": "error", "msg": "2FA code required"})
    
    try:
        wrapper_process.stdin.write(f"{two_fa_code}\n")
        wrapper_process.stdin.flush()
        add_log(wrapper_logs, "2FA code submitted")
        wrapper_needs_2fa = False
        return jsonify({"status": "ok", "msg": "2FA code submitted"})
    except Exception as e:
        add_log(wrapper_logs, f"Error submitting 2FA code: {str(e)}")
        return jsonify({"status": "error", "msg": f"Failed to submit 2FA code: {str(e)}"})


@app.route("/download", methods=["POST"])
def download():
    global download_running, last_download
    
    link = (request.form.get("link") or "").strip()
    format_choice = request.form.get("format")
    special_audio = request.form.get("special_audio") == "true"
    select_all = request.form.get("select_all") == "true"
    
    if not wrapper_running:
        return jsonify({"status": "error", "msg": "Wrapper not running"})
    
    if not link:
        return jsonify({"status": "error", "msg": "No URL provided"})

    if not is_apple_music_url(link):
        return jsonify({"status": "error", "msg": "Invalid link, paste an https://music.apple.com link"})

    if special_audio:
        if format_choice == "ATMOS":
            cmd = amd_command("--atmos", link)
            label = "ATMOS"
        elif format_choice == "AAC":
            cmd = amd_command("--aac", link)
            label = "AAC"
        else:
            return jsonify({"status": "error", "msg": "Invalid format selected"})
    else:
        cmd = amd_command(link)
        label = "standard"

    with download_lock:
        if download_running:
            return jsonify({"status": "error", "msg": "Download already in progress"})
        download_running = True

    amd_dir = AMD_DIR
    add_log(downloader_logs, f"Starting {label} download: {link}")
    if select_all:
        add_log(downloader_logs, "Option All: every selection prompt will be answered with 'all'")
    add_log(downloader_logs, f"Working directory: {amd_dir}")
    add_log(downloader_logs, f"Executing: {' '.join(cmd)}")
    
    try:
        last_download = {"cmd": cmd, "select_all": select_all}
        launch_download(cmd, select_all)
        return jsonify({"status": "ok", "msg": "Download started successfully"})
    except Exception as e:
        download_running = False
        add_log(downloader_logs, f"Error starting download: {str(e)}")
        return jsonify({"status": "error", "msg": f"Failed to start download: {str(e)}"})


@app.route("/pause_download", methods=["POST"])
def pause_download():
    global download_paused
    with download_lock:
        if not download_running or download_paused:
            return jsonify({"status": "error", "msg": "No running download to pause"})
        if not signal_download(signal.SIGSTOP):
            return jsonify({"status": "error", "msg": "Could not pause the download"})
        download_paused = True
    add_log(downloader_logs, "Download paused")
    return jsonify({"status": "ok", "msg": "Download paused"})

@app.route("/resume_download", methods=["POST"])
def resume_download():
    global download_paused
    with download_lock:
        if not download_running or not download_paused:
            return jsonify({"status": "error", "msg": "No paused download to resume"})
        if not signal_download(signal.SIGCONT):
            return jsonify({"status": "error", "msg": "Could not resume the download"})
        download_paused = False
    add_log(downloader_logs, "Download resumed")
    return jsonify({"status": "ok", "msg": "Download resumed"})

@app.route("/restart_download", methods=["POST"])
def restart_download():
    global download_process, download_running, download_paused
    with download_lock:
        if not download_running or not last_download:
            return jsonify({"status": "error", "msg": "No download to restart"})
        old = download_process
        download_process = None
        if old is not None and old.poll() is None:
            try:
                group = os.getpgid(old.pid)
                os.killpg(group, signal.SIGCONT)
                os.killpg(group, signal.SIGTERM)
                try:
                    old.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(group, signal.SIGKILL)
                    old.wait(timeout=5)
            except (ProcessLookupError, PermissionError, OSError, subprocess.TimeoutExpired):
                pass
        add_log(downloader_logs, "Download restarted from the beginning")
        try:
            launch_download(last_download["cmd"], last_download["select_all"])
        except Exception as e:
            download_running = False
            download_paused = False
            add_log(downloader_logs, f"Error restarting download: {str(e)}")
            return jsonify({"status": "error", "msg": f"Failed to restart download: {str(e)}"})
    return jsonify({"status": "ok", "msg": "Download restarted"})

@app.route("/get_logs")
def get_logs():
    global wrapper_running, download_running, download_paused

    if wrapper_process and wrapper_process.poll() is not None:
        wrapper_running = False
    
    if download_process and download_process.poll() is not None:
        download_running = False
        download_paused = False
    
    with log_lock:
        wrapper_snapshot = wrapper_logs[-200:]
        downloader_snapshot = downloader_logs[-200:]

    return jsonify({
        "wrapper": wrapper_snapshot,
        "downloader": downloader_snapshot,
        "wrapper_running": wrapper_running,
        "download_running": download_running,
        "download_paused": download_paused,
        "amd_state": amd_state(),
        "wrapper_needs_2fa": wrapper_needs_2fa
    })

@app.route("/stop_wrapper", methods=["POST"])
def stop_wrapper():
    global wrapper_running, wrapper_needs_2fa, wrapper_stop_requested
    
    if wrapper_process and wrapper_process.poll() is None:
        wrapper_stop_requested = True
        wrapper_process.terminate()
        add_log(wrapper_logs, "Wrapper process terminated by user")
        wrapper_running = False
        wrapper_needs_2fa = False
        return jsonify({"status": "ok", "msg": "Wrapper stopped"})
    else:
        return jsonify({"status": "error", "msg": "Wrapper not running"})

@app.route("/settings")
def settings():
    prefs = read_prefs()
    return render_template("Settings.html", theme=prefs["theme"], language=prefs["language"], advanced=prefs["advanced_settings"])

@app.route("/get_config")
def get_config():
    try:
        Start.prepare_user_data()
        config_path = CONFIG_PATH
        
        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
            return jsonify({"status": "ok", "config": config})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@app.route("/save_config", methods=["POST"])
def save_config():
    try:
        config_path = CONFIG_PATH
        
        config_data = request.json

        integer_fields = {
            'alac-max', 'atmos-max', 'limit-max', 'max-memory-limit', 'mv-max'
        }
        
        boolean_fields = {
            'embed-lrc', 'save-lrc-file', 'save-artist-cover', 'save-animated-artwork',
            'emby-animated-artwork', 'embed-cover', 'get-m3u8-from-device',
            'use-songinfo-for-playlist', 'dl-albumcover-for-playlist',
            'convert-after-download', 'convert-keep-original', 'convert-skip-if-source-matches'
        }

        path_fields = {
            'alac-save-folder', 'atmos-save-folder', 'aac-save-folder',
            'flac-save-folder', 'wav-save-folder', 'mp3-save-folder'
        }
        
        def translate_path_to_wsl(path):
            """Translate Windows paths to WSL paths when saving config"""
            if not path:
                return path
            if len(path) >= 3 and path[1:3] == ':\\':
                drive = path[0].lower()
                rest = path[3:].replace('\\', '/')
                return f"/mnt/{drive}/{rest}"
            elif len(path) >= 3 and path[1:3] == ':/':
                drive = path[0].lower()
                rest = path[3:]
                return f"/mnt/{drive}/{rest}"
            return path
        
        integer_defaults = {'limit-max': 200}
        
        for key, value in config_data.items():
            if key in integer_fields:
                default = integer_defaults.get(key, 0)
                try:
                    config_data[key] = int(value) if value else default
                except (ValueError, TypeError):
                    config_data[key] = default
            elif key in boolean_fields:
                if isinstance(value, str):
                    config_data[key] = value.lower() in ('true', '1', 'yes', 'on')
                else:
                    config_data[key] = bool(value)
            elif key in path_fields:
                config_data[key] = translate_path_to_wsl(str(value))
        try:
            with open(config_path, 'r', encoding='utf-8') as file:
                merged = yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError):
            merged = {}
        merged.update(config_data)
        with open(config_path, 'w', encoding='utf-8') as file:
            yaml.dump(merged, file, default_flow_style=False, allow_unicode=True, sort_keys=False)
            
        return jsonify({"status": "ok", "msg": "Configuration saved successfully"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@app.route("/check_saved_credentials")
def check_saved_credentials():
    """Check if saved credentials exist"""
    email, password = load_credentials()
    return jsonify({"has_credentials": email is not None, "email": email if email else ""})

@app.route("/delete_saved_credentials", methods=["POST"])
def delete_saved_credentials():
    """Delete saved credentials"""
    if delete_credentials():
        return jsonify({"status": "ok", "msg": "Saved credentials deleted"})
    else:
        return jsonify({"status": "error", "msg": "Failed to delete credentials"})

@app.route("/auto_login", methods=["POST"])
def auto_login():
    """Attempt auto-login with saved credentials"""
    remaining = auto_login_lock_remaining()
    if remaining:
        return jsonify({"status": "error", "msg": f"Auto-login is locked, try again in {format_wait(remaining)}"})
    if attempt_auto_login():
        return jsonify({"status": "ok", "msg": "Auto-login started"})
    else:
        return jsonify({"status": "error", "msg": "No saved credentials or login failed"})

@app.route("/get_download_folders")
def get_download_folders():
    """Get download folder paths from config with Windows to WSL path translation"""
    try:
        config_path = CONFIG_PATH
        
        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
        folders = {
            "alac": config.get("alac-save-folder") or "Downloads/ALAC",
            "flac": config.get("flac-save-folder") or "Downloads/FLAC",
            "wav": config.get("wav-save-folder") or "Downloads/WAV",
            "atmos": config.get("atmos-save-folder") or "Downloads/Atmos",
            "aac": config.get("aac-save-folder") or "Downloads/AAC",
            "mp3": config.get("mp3-save-folder") or "Downloads/MP3"
        }
        
        return jsonify({"status": "ok", "folders": folders})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

def get_prefs_path():
    os.makedirs(USER_DIR, exist_ok=True)
    return os.path.join(USER_DIR, "prefs.json")

def read_prefs():
    prefs = dict(DEFAULT_PREFS)
    try:
        with open(get_prefs_path(), 'r') as f:
            stored = json.load(f)
        if isinstance(stored, dict):
            prefs.update(stored)
    except (OSError, ValueError):
        pass
    return prefs

@app.route("/get_prefs")
def get_prefs():
    return jsonify(read_prefs())

@app.route("/save_prefs", methods=["POST"])
def save_prefs():
    data = request.json or {}
    prefs = read_prefs()
    if "special_audio" in data:
        prefs["special_audio"] = bool(data["special_audio"])
    if "select_all" in data:
        prefs["select_all"] = bool(data["select_all"])
    if data.get("format") in ("ATMOS", "AAC"):
        prefs["format"] = data["format"]
    if "advanced_settings" in data:
        prefs["advanced_settings"] = bool(data["advanced_settings"])
    if data.get("theme") in ("dark", "light"):
        prefs["theme"] = data["theme"]
    if data.get("language") in ("en", "pl"):
        prefs["language"] = data["language"]
    try:
        with open(get_prefs_path(), 'w') as f:
            json.dump(prefs, f)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})
