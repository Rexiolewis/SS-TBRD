import json
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
LOG_DIR = ROOT_DIR / "logs"
CONTROL_FILE = LOG_DIR / "bot_control.json"
PID_FILE = LOG_DIR / "bot.pid"
BOT_LOG_FILE = LOG_DIR / "bot_stdout.log"


def _ensure_log_dir():
    LOG_DIR.mkdir(exist_ok=True)


def _utc_now():
    return datetime.utcnow().isoformat()


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path, payload):
    _ensure_log_dir()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def set_bot_enabled(enabled):
    _write_json(CONTROL_FILE, {"enabled": bool(enabled), "updated_at": _utc_now()})


def should_keep_running():
    state = _read_json(CONTROL_FILE, {"enabled": True})
    return bool(state.get("enabled", True))


def mark_bot_started(pid=None):
    _ensure_log_dir()
    set_bot_enabled(True)
    PID_FILE.write_text(str(pid or os.getpid()), encoding="utf-8")


def mark_bot_stopped():
    set_bot_enabled(False)
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def get_bot_pid():
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _is_windows_pid_running(pid):
    import ctypes

    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    wait_timeout = 0x00000102

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query_limited_information | synchronize, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        kernel32.CloseHandle(handle)


def is_process_running(pid):
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        return _is_windows_pid_running(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_bot_running():
    pid = get_bot_pid()
    running = is_process_running(pid)
    if pid and not running:
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass
    return running


def start_bot():
    if is_bot_running():
        return {"ok": False, "reason": "Bot is already running", "pid": get_bot_pid()}

    _ensure_log_dir()
    set_bot_enabled(True)
    log = BOT_LOG_FILE.open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, str(ROOT_DIR / "app.py")],
        cwd=str(ROOT_DIR),
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    return {"ok": True, "reason": "Bot started", "pid": process.pid}


def request_stop_bot():
    set_bot_enabled(False)
    pid = get_bot_pid()
    return {"ok": True, "reason": "Stop requested", "pid": pid}


def force_stop_bot():
    pid = get_bot_pid()
    if not pid:
        return {"ok": False, "reason": "No bot PID found", "pid": None}

    if not is_process_running(pid):
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass
        return {"ok": False, "reason": "Bot process is not running", "pid": pid}

    os.kill(pid, signal.SIGTERM)
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass
    return {"ok": True, "reason": "Bot process terminated", "pid": pid}
