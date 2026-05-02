"""
Windsurf desktop app account switching -- pure protocol implementation
Supports macOS / Windows / Linux

Switching flow (no browser needed, no Electron safeStorage manipulation):
1. Use session_token to call GetOneTimeAuthToken API to obtain a one-time OTT
2. Pass the OTT to Windsurf desktop via windsurf:// deep link
3. Windsurf internally uses the OTT to complete authentication and switch account

Windsurf authentication info is cached in the state.vscdb SQLite database:
  macOS:   ~/Library/Application Support/Windsurf/User/globalStorage/state.vscdb
  Windows: %APPDATA%/Windsurf/User/globalStorage/state.vscdb
  Linux:   ~/.config/Windsurf/User/globalStorage/state.vscdb
"""

import json
import logging
import os
import platform
import sqlite3
import subprocess
import time
from typing import Tuple
from urllib.parse import quote

from core.desktop_apps import build_desktop_app_state

logger = logging.getLogger(__name__)

_DB_KEY = "windsurfAuthStatus"


def _get_windsurf_config_dir() -> str:
    """Get Windsurf configuration directory path"""
    system = platform.system()

    if system == "Darwin":
        home = os.path.expanduser("~")
        return os.path.join(home, "Library", "Application Support", "Windsurf", "User")

    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "Windsurf", "User")

    else:  # Linux
        home = os.path.expanduser("~")
        config_home = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
        return os.path.join(config_home, "Windsurf", "User")


def _get_windsurf_db_path() -> str:
    """Get Windsurf state.vscdb path"""
    config_dir = _get_windsurf_config_dir()
    return os.path.join(config_dir, "globalStorage", "state.vscdb")


def _windsurf_install_paths() -> list[str]:
    system = platform.system()
    if system == "Darwin":
        home = os.path.expanduser("~")
        return [
            "/Applications/Windsurf.app",
            os.path.join(home, "Applications", "Windsurf.app"),
        ]
    if system == "Windows":
        localappdata = os.environ.get("LOCALAPPDATA", "")
        return [os.path.join(localappdata, "Programs", "Windsurf", "Windsurf.exe")]
    return ["/usr/bin/windsurf", os.path.expanduser("~/.local/bin/windsurf")]


def _windsurf_process_patterns() -> list[str]:
    system = platform.system()
    if system == "Darwin":
        return [
            "/Applications/Windsurf.app/Contents/MacOS/Electron",
            os.path.join(os.path.expanduser("~"), "Applications", "Windsurf.app", "Contents", "MacOS", "Electron"),
        ]
    if system == "Windows":
        return ["Windsurf.exe"]
    return ["windsurf"]


def _read_db_key(db_path: str, key: str) -> str | None:
    """Read the value for the specified key from state.vscdb"""
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            row = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to read state.vscdb: {e}")
        return None


def _write_db_key(db_path: str, key: str, value: str):
    """Write a value for the specified key to state.vscdb (INSERT OR REPLACE)"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value TEXT)",
        )
        conn.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def _clear_old_auth_keys(db_path: str):
    """Clear old account encrypted session and auth cache from state.vscdb"""
    if not os.path.exists(db_path):
        return
    # Key patterns to delete:
    # - secret://...windsurf_auth.sessions  (Electron safeStorage encrypted session)
    # - secret://...windsurf_auth.apiServerUrl
    # - codeium.windsurf-windsurf_auth      (current username)
    # - codeium.windsurf-windsurf_auth-     (session UUID)
    # - windsurf_auth-*                     (user session reference)
    # - windsurf.settings.cachedPlanInfo    (cached plan info)
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            conn.execute("DELETE FROM ItemTable WHERE key LIKE 'secret://%windsurf_auth%'")
            conn.execute("DELETE FROM ItemTable WHERE key LIKE 'codeium.windsurf-windsurf_auth%'")
            conn.execute("DELETE FROM ItemTable WHERE key LIKE 'windsurf_auth-%'")
            conn.execute("DELETE FROM ItemTable WHERE key = 'windsurf.settings.cachedPlanInfo'")
            conn.commit()
            logger.info("Cleared Windsurf old session cache")
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to clear old auth keys (non-fatal): {e}")


def _get_one_time_auth_token(session_token: str, proxy: str | None = None) -> str:
    """Use session_token to call GetOneTimeAuthToken to obtain a one-time auth token"""
    from platforms.windsurf.core import WindsurfClient, _field_string

    api_key = session_token
    if not api_key.startswith("devin-session-token$"):
        api_key = f"devin-session-token${session_token}"

    client = WindsurfClient(proxy=proxy, log_fn=lambda x: None)
    raw = client._proto_post("GetOneTimeAuthToken", _field_string(1, api_key))
    # protobuf field 1 (wire type 2): tag=0x0a, next byte=length, then string
    if len(raw) < 3 or raw[0] != 0x0A:
        raise RuntimeError(f"GetOneTimeAuthToken returned unexpected format: {raw[:20].hex()}")
    length = raw[1]
    ott = raw[2 : 2 + length].decode("utf-8")
    if not ott:
        raise RuntimeError("GetOneTimeAuthToken returned empty OTT")
    return ott


def _open_deep_link(ott: str) -> bool:
    """Pass OTT to Windsurf desktop via windsurf:// deep link"""
    deep_link = f"windsurf://codeium.windsurf#state=switch&access_token={quote(ott, safe='')}"
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", deep_link], timeout=5)
        elif system == "Windows":
            os.startfile(deep_link)
        else:
            subprocess.run(["xdg-open", deep_link], timeout=5)
        return True
    except Exception as e:
        logger.error(f"Failed to open deep link: {e}")
        return False


def switch_windsurf_account(
    *,
    session_token: str,
    proxy: str | None = None,
) -> Tuple[bool, str]:
    """
    Switch Windsurf desktop app account (pure protocol, no browser needed)

    Flow:
    1. Use session_token to call GetOneTimeAuthToken API -> obtain OTT
    2. Pass OTT to Windsurf via windsurf:// deep link -> complete auth switch

    Returns:
        (success, message)
    """
    if not session_token:
        return False, "Missing session_token, cannot switch"

    try:
        ott = _get_one_time_auth_token(session_token, proxy=proxy)
        logger.info(f"Obtained OTT successfully: {ott[:20]}...")

        if not _open_deep_link(ott):
            return False, "OTT obtained successfully but failed to open deep link, please open Windsurf manually"

        return True, "Windsurf account switch command sent, please confirm in Windsurf"

    except Exception as e:
        logger.error(f"Windsurf account switch failed: {e}")
        return False, f"Switch failed: {str(e)}"


def restart_windsurf_ide() -> Tuple[bool, str]:
    """Close and restart Windsurf IDE"""
    system = platform.system()

    try:
        if system == "Darwin":
            subprocess.run(
                ["osascript", "-e", 'quit app "Windsurf"'],
                capture_output=True,
                timeout=5,
            )
            time.sleep(2.0)

            for app_path in _windsurf_install_paths():
                if app_path.endswith(".app") and os.path.exists(app_path):
                    subprocess.Popen(["open", "-a", app_path])
                    return True, "Windsurf IDE restarted"
            return True, "Windsurf IDE closed (application path not found, please start manually)"

        elif system == "Windows":
            subprocess.run(
                ["taskkill", "/IM", "Windsurf.exe", "/F"],
                capture_output=True,
                creationflags=0x08000000,
                timeout=5,
            )
            time.sleep(1.5)

            for exe_path in _windsurf_install_paths():
                if os.path.exists(exe_path):
                    subprocess.Popen([exe_path])
                    return True, "Windsurf IDE restarted"
            return True, "Windsurf IDE closed (application path not found, please start manually)"

        else:  # Linux
            subprocess.run(["pkill", "-f", "windsurf"], capture_output=True, timeout=5)
            time.sleep(1.5)

            for path in ["/usr/bin/windsurf", os.path.expanduser("~/.local/bin/windsurf")]:
                if os.path.exists(path):
                    subprocess.Popen([path])
                    return True, "Windsurf IDE restarted"

            try:
                subprocess.Popen(["windsurf"])
                return True, "Windsurf IDE restarted"
            except FileNotFoundError:
                return True, "Windsurf IDE closed (application path not found, please start manually)"

    except Exception as e:
        logger.error(f"Windsurf IDE restart failed: {e}")
        return False, f"Restart failed: {str(e)}"


def read_current_windsurf_account() -> dict | None:
    """Read the current Windsurf IDE account info"""
    db_path = _get_windsurf_db_path()
    raw = _read_db_key(db_path, _DB_KEY)
    if not raw:
        return None

    try:
        auth_data = json.loads(raw)
    except Exception:
        return None

    api_key = str(auth_data.get("apiKey") or "")
    if not api_key:
        return None

    # apiKey format: "devin-session-token$<JWT>"
    session_token = api_key
    if api_key.startswith("devin-session-token$"):
        session_token = api_key[len("devin-session-token$"):]

    return {
        "session_token": session_token,
        "api_key_raw": api_key,
    }


def get_windsurf_desktop_state() -> dict:
    """Get Windsurf desktop app state"""
    current = read_current_windsurf_account() or {}
    db_path = _get_windsurf_db_path()
    config_dir = _get_windsurf_config_dir()
    state = build_desktop_app_state(
        app_id="windsurf",
        app_name="Windsurf",
        process_patterns=_windsurf_process_patterns(),
        install_paths=_windsurf_install_paths(),
        binary_names=["windsurf"],
        config_paths=[config_dir, db_path],
        current_account_present=bool(current.get("session_token")),
        extra={
            "db_path": db_path,
        },
    )
    state["available"] = True
    return state
