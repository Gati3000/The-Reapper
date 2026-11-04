"""Entry point: verify the installation, then start the web UI."""
import os
import re
import sys
import threading
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "App" / "Launcher"))
# mus sie importowac przed  bo nie bedzie sciezek tych wyrzej napisanych 
import Start

LOG_FLAG_NAME = ".log_enabled"
LOG_FILE_NAME = "reapper.log"
LOG_MAX_BYTES = 5 * 1024 * 1024 
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

#  Slabe logi do poprawy kiedys ale juz sa to sbie pokorzystam
class _LogSink:
    def __init__(self, user_dir):
        self.flag = Path(user_dir) / LOG_FLAG_NAME
        self.path = Path(user_dir) / LOG_FILE_NAME
        self.lock = threading.Lock()
        self.active = False
        self.at_line_start = True

    def _append(self, text):
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", errors="replace") as f:
            f.write(text)

    def write(self, data):
        try:
            with self.lock:
                if not self.flag.exists():
                    self.active = False
                    return
                if not self.active:
                    self.active = True
                    self.at_line_start = True
                    try:
                        if self.path.stat().st_size > LOG_MAX_BYTES:
                            os.replace(self.path, str(self.path) + ".old")
                    except FileNotFoundError:
                        pass
                    self._append(time.strftime("%Y-%m-%d %H:%M:%S") + " --- logging started ---\n")
                out = []
                for chunk in _ANSI.sub("", data).replace("\r\n", "\n").replace("\r", "\n").splitlines(True):
                    if self.at_line_start:
                        out.append(time.strftime("%Y-%m-%d %H:%M:%S") + " ")
                    out.append(chunk)
                    self.at_line_start = chunk.endswith("\n")
                if out:
                    self._append("".join(out))
        except Exception:
            pass 


class _Tee:
    def __init__(self, stream, sink):
        self._stream = stream
        self._sink = sink

    def write(self, data):
        written = self._stream.write(data)
        if isinstance(data, str) and data:
            self._sink.write(data)
        return written

    def __getattr__(self, name): 
        return getattr(self._stream, name)


def install_log_tee(user_dir=None):
    sink = _LogSink(user_dir if user_dir is not None else Start.USER_DIR)
    sys.stdout = _Tee(sys.stdout, sink)
    sys.stderr = _Tee(sys.stderr, sink)
    return sink


def main():
    install_log_tee()
    Start.setup_path()
    problems = Start.check()
    if problems:
        print("The Reapper cannot start. Missing or outdated components:\n")
        for item in problems:
            print(f"  - {item.label}: {item.detail}")
        print("\nFix it with:  sudo rip update")
        print(f"Without the rip command:  sudo python3 {Start.LAUNCHER_DIR / 'Start.py'} update")
        return 1

    Start.prepare_user_data()
    from App import app
# Its not save bo it works on LAN so its fine XD i dont want to create login 
# but yeah mby in future ill change it so its saver or sum
    host = os.environ.get("REAPPER_HOST", "0.0.0.0")
    try:
       port = int(os.environ.get("REAPPER_PORT", "5000"))
       if not 1 <= port <= 65535:
           raise ValueError
    except ValueError:
        print(f"Invalid REAPPER_PORT: {os.environ.get('REAPPER_PORT')!r}. Use a number between 1 and 65535.")
        return 1
    print(f"Starting The Reapper on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
    return 0

if __name__ == "__main__":
    sys.exit(main())
