from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
LAUNCHER_DIR = APP_DIR / "Launcher"
USER_DIR = PROJECT_DIR / "User"
AMD_DIR = PROJECT_DIR / "apple-music-downloader"

CONFIG_FILE = USER_DIR / "config.yaml"
EXAMPLE_CONFIG = LAUNCHER_DIR / "Example-Config.yaml"
AMD_CONFIG = AMD_DIR / "config.yaml"

MANIFEST_FILE = APP_DIR / "Manifest.ini"
DEFAULTS_FILE = APP_DIR / "Defaults.ini"

AMD_BINARY = AMD_DIR / "amd"
AMD_BUILD_FILE = AMD_DIR / ".amd_build"

SYSTEM_BIN = Path("/usr/local/bin")

WRAPPER_DIR = PROJECT_DIR / "wrapper"
BENTO4_DIR = PROJECT_DIR / "bento4"

CREDENTIALS_FILE = USER_DIR / ".credentials"
RIP_SCRIPT = LAUNCHER_DIR / "rip"

GO_ROOT = Path("/usr/local/go")
AUTO_LOGIN_FILE = USER_DIR / ".auto_login"
