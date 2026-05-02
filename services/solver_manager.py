"""Turnstile Solver process management — automatically started when backend launches"""
import subprocess
import sys
import os
import time
import threading
import signal
import requests

SOLVER_PORT = 8889
SOLVER_URL = f"http://localhost:{SOLVER_PORT}"
_proc: subprocess.Popen = None
_lock = threading.Lock()

# Consecutive startup failure count to prevent infinite retry loops
_consecutive_failures = 0
_MAX_CONSECUTIVE_FAILURES = 3
_last_failure_reason = ""


def is_running() -> bool:
    try:
        r = requests.get(f"{SOLVER_URL}/", timeout=2)
        return r.status_code < 500
    except Exception:
        return False


def get_status() -> dict:
    """Return detailed solver status for API use."""
    running = is_running()
    info: dict = {"running": running}
    if not running and _last_failure_reason:
        info["last_error"] = _last_failure_reason
    if not running and _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        info["stopped_retrying"] = True
        info["message"] = f"Failed to start {_consecutive_failures} consecutive times, stopped retrying. Please investigate and restart manually."
    return info


def _ensure_camoufox_browser() -> bool:
    """Check if Camoufox browser binary is downloaded; auto-fetch if not installed.

    Returns True if ready, False if download failed (network issues, etc.). Called before Solver startup.
    First download is approximately 100MB, cached and skipped afterwards.
    """
    try:
        from camoufox.pkgman import installed_verstr, CamoufoxNotInstalled
    except Exception as e:
        print(f"[Solver] Failed to import camoufox library: {e}")
        return False

    try:
        ver = installed_verstr()
        print(f"[Solver] Camoufox browser is ready (v{ver})")
        return True
    except CamoufoxNotInstalled:
        pass
    except Exception as e:
        print(f"[Solver] Camoufox browser detection error, attempting to install anyway: {e}")

    print("[Solver] Camoufox browser not installed, starting download (approximately 100MB, please wait)...")
    try:
        from camoufox.pkgman import CamoufoxFetcher
        CamoufoxFetcher().install()
        print("[Solver] Camoufox browser download completed")
        return True
    except Exception as e:
        print(f"[Solver] Camoufox browser download failed: {e}")
        return False


def start():
    global _proc, _consecutive_failures, _last_failure_reason
    with _lock:
        if is_running():
            print("[Solver] Already running")
            _consecutive_failures = 0
            _last_failure_reason = ""
            return

        # Too many consecutive failures, refusing to retry (manual restart resets the counter)
        if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            print(f"[Solver] Failed to start {_consecutive_failures} consecutive times, stopped retrying. Please investigate and restart manually.")
            return

        # Ensure Camoufox browser binary is available before starting Solver subprocess
        if not _ensure_camoufox_browser():
            _consecutive_failures += 1
            _last_failure_reason = "Camoufox browser not available"
            print("[Solver] Skipping Solver startup because Camoufox browser is not available")
            return

        # After PyInstaller packaging, sys.executable points to the backend executable,
        # use --solver argument to enter solver entry; in source mode use python + start.py
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--solver",
                   "--browser_type", "camoufox",
                   "--thread", "1",
                   "--port", str(SOLVER_PORT)]
        else:
            solver_script = os.path.join(
                os.path.dirname(__file__), "turnstile_solver", "start.py"
            )
            cmd = [sys.executable, solver_script,
                   "--browser_type", "camoufox",
                   "--thread", "1",
                   "--port", str(SOLVER_PORT)]
        _proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        # Wait for service to be ready (up to 30s)
        for _ in range(30):
            time.sleep(1)
            if _proc.poll() is not None:
                # Subprocess has exited, read stderr
                stderr_msg = ""
                try:
                    stderr_msg = _proc.stderr.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                _consecutive_failures += 1
                _last_failure_reason = stderr_msg or f"Process exited with code={_proc.returncode}"
                print(f"[Solver] Subprocess exited unexpectedly with code={_proc.returncode} (consecutive failures {_consecutive_failures}/{_MAX_CONSECUTIVE_FAILURES})")
                if stderr_msg:
                    print(f"[Solver] stderr: {stderr_msg}")
                _proc = None
                return
            if is_running():
                print(f"[Solver] Started PID={_proc.pid}")
                _consecutive_failures = 0
                _last_failure_reason = ""
                # Close stderr pipe to prevent subprocess blocking from full buffer
                try:
                    _proc.stderr.close()
                except Exception:
                    pass
                return
        # Startup timeout
        _consecutive_failures += 1
        stderr_msg = ""
        if _proc and _proc.stderr:
            try:
                import select
                if select.select([_proc.stderr], [], [], 0)[0]:
                    stderr_msg = _proc.stderr.read(2000).decode("utf-8", errors="replace")
                _proc.stderr.close()
            except Exception:
                pass
        _last_failure_reason = f"Startup timeout {stderr_msg}".strip()
        print(f"[Solver] Startup timeout (consecutive failures {_consecutive_failures}/{_MAX_CONSECUTIVE_FAILURES})"
              f"{' stderr: ' + stderr_msg if stderr_msg else ''}")


def stop():
    global _proc
    with _lock:
        # 1. First terminate the subprocess we spawned
        if _proc and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proc.kill()
                _proc.wait(timeout=3)
            print("[Solver] Subprocess stopped")
        _proc = None

        # 2. Even if _proc is empty (Docker / external startup), try to find and kill residual processes by port
        if is_running():
            _kill_by_port(SOLVER_PORT)
            for _ in range(10):
                time.sleep(0.5)
                if not is_running():
                    break
            if is_running():
                print("[Solver] Warning: Port still in use after stopping")
            else:
                print("[Solver] Residual process cleaned up")


def _kill_by_port(port: int):
    """Find and kill the process occupying the given port (cross-platform)."""
    import platform
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"], text=True, timeout=5
            )
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    if pid > 0:
                        os.kill(pid, signal.SIGTERM)
        else:
            out = subprocess.check_output(
                ["lsof", "-ti", f":{port}"], text=True, timeout=5
            ).strip()
            for pid_str in out.splitlines():
                pid = int(pid_str.strip())
                if pid > 0 and pid != os.getpid():
                    os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def restart():
    """Synchronous restart: stop -> wait for port release -> start. Manual restart resets the failure counter."""
    global _consecutive_failures, _last_failure_reason
    _consecutive_failures = 0
    _last_failure_reason = ""
    stop()
    # Wait for port to be fully released, up to 5 seconds
    for _ in range(10):
        if not is_running():
            break
        time.sleep(0.5)
    start()


def start_async():
    """Start in a background thread without blocking the main process"""
    t = threading.Thread(target=start, daemon=True)
    t.start()
