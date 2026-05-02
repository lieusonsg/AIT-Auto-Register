"""
Trae.ai account switching -- write to local config file, Trae IDE auto-detects
Supports macOS / Windows / Linux
"""

import os
import json
import logging
import tempfile
import platform
import subprocess
import time
from typing import Tuple

logger = logging.getLogger(__name__)


def _get_trae_config_dir() -> str:
    """Get Trae configuration directory path"""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        home = os.path.expanduser("~")
        return os.path.join(home, "Library", "Application Support", "Trae", "User")
    
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "Trae", "User")
    
    else:  # Linux
        home = os.path.expanduser("~")
        config_home = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
        return os.path.join(config_home, "Trae", "User")


def _get_trae_storage_path() -> str:
    """Get Trae storage.json path"""
    config_dir = _get_trae_config_dir()
    return os.path.join(config_dir, "globalStorage", "storage.json")


def _atomic_write(filepath: str, content: str):
    """Atomic write: write temp file first, then rename"""
    dir_path = os.path.dirname(filepath)
    os.makedirs(dir_path, exist_ok=True)
    
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp_path, filepath)
    except Exception:
        try:
            os.close(fd)
        except:
            pass
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def switch_trae_account(
    token: str,
    user_id: str = "",
    email: str = "",
    region: str = ""
) -> Tuple[bool, str]:
    """
    Switch Trae account (write to storage.json, requires Trae restart)

    Args:
        token: Trae API token
        user_id: User ID
        email: Email
        region: Region

    Returns:
        (success, message)
    """
    try:
        storage_path = _get_trae_storage_path()
        
        # Read existing config
        storage_data = {}
        if os.path.exists(storage_path):
            try:
                with open(storage_path, "r", encoding="utf-8") as f:
                    storage_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read existing config, will create new config: {e}")
        
        # Update token and user info
        storage_data["trae.token"] = token
        if user_id:
            storage_data["trae.userId"] = user_id
        if email:
            storage_data["trae.email"] = email
        if region:
            storage_data["trae.region"] = region
        
        # Atomic write
        content = json.dumps(storage_data, indent=2, ensure_ascii=False)
        _atomic_write(storage_path, content)
        
        return True, "Switch successful, please restart Trae IDE for the new account to take effect"
    
    except Exception as e:
        logger.error(f"Trae account switch failed: {e}")
        return False, f"Switch failed: {str(e)}"


def restart_trae_ide() -> Tuple[bool, str]:
    """Close and restart Trae IDE"""
    system = platform.system()
    
    try:
        if system == "Darwin":  # macOS
            # Close Trae
            subprocess.run(
                ["osascript", "-e", 'quit app "Trae"'],
                capture_output=True,
                timeout=5
            )
            time.sleep(2.0)

            # Start Trae
            trae_app = "/Applications/Trae.app"
            if os.path.exists(trae_app):
                subprocess.Popen(["open", "-a", "Trae"])
                return True, "Trae IDE restarted"
            return True, "Trae IDE closed (application path not found, please start manually)"
        
        elif system == "Windows":
            # Close Trae
            subprocess.run(
                ["taskkill", "/IM", "Trae.exe", "/F"],
                capture_output=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                timeout=5
            )
            time.sleep(1.5)

            # Start Trae
            localappdata = os.environ.get("LOCALAPPDATA", "")
            trae_exe = os.path.join(localappdata, "Programs", "Trae", "Trae.exe")
            if os.path.exists(trae_exe):
                subprocess.Popen([trae_exe])
                return True, "Trae IDE restarted"
            return True, "Trae IDE closed (application path not found, please start manually)"
        
        else:  # Linux
            # Close Trae
            subprocess.run(["pkill", "-f", "trae"], capture_output=True, timeout=5)
            time.sleep(1.5)

            # Start Trae
            for path in ["/usr/bin/trae", os.path.expanduser("~/.local/bin/trae")]:
                if os.path.exists(path):
                    subprocess.Popen([path])
                    return True, "Trae IDE restarted"

            try:
                subprocess.Popen(["trae"])
                return True, "Trae IDE restarted"
            except FileNotFoundError:
                return True, "Trae IDE closed (application path not found, please start manually)"
    
    except Exception as e:
        logger.error(f"Trae IDE restart failed: {e}")
        return False, f"Restart failed: {str(e)}"


def read_current_trae_account() -> dict | None:
    """Read current Trae IDE account info"""
    storage_path = _get_trae_storage_path()
    
    if not os.path.exists(storage_path):
        return None
    
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            storage_data = json.load(f)
        
        token = storage_data.get("trae.token")
        if token:
            return {
                "token": token,
                "user_id": storage_data.get("trae.userId", ""),
                "email": storage_data.get("trae.email", ""),
                "region": storage_data.get("trae.region", "")
            }
        return None
    
    except Exception as e:
        logger.error(f"Failed to read Trae config: {e}")
        return None


def get_trae_user_info(token: str) -> dict | None:
    """Get user info via token"""
    from curl_cffi import requests as curl_req
    
    try:
        r = curl_req.post(
            "https://api-sg-central.trae.ai/cloudide/api/v3/common/GetUserToken",
            headers={
                "Authorization": f"Cloud-IDE-JWT {token}",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/145.0.0.0 Safari/537.36"
            },
            json={},
            impersonate="chrome124",
            timeout=15,
        )
        
        if r.status_code == 200:
            return r.json()
        return None
    
    except Exception as e:
        logger.error(f"Failed to get Trae user info: {e}")
        return None
