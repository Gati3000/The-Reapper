"""Entry point: verify the installation, then start the web UI."""
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "App" / "Launcher"))
# Star must be imported after path 7,8 are set so dont change it
import Start

def main():
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
