import json
import logging
import os
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import blinkt
    BLINKT_AVAILABLE = True
except ImportError:
    BLINKT_AVAILABLE = False

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Bin LED Web UI")

LED_SERVICE_DIR = Path(os.environ.get("LED_SERVICE_DIR", "/home/pizero2/blinkt-projects/bin-led-reminder"))
SCHEDULE_FILE = LED_SERVICE_DIR / "recycling_schedule.json"
CONFIG_FILE = LED_SERVICE_DIR / "config.json"
ERROR_FILE = LED_SERVICE_DIR / "error_state.json"
LOG_FILE = LED_SERVICE_DIR / "logs/bin_led_service.log"

STATIC_DIR = Path(__file__).parent / "static"

# Logging — writes to the same log file as the LED service so the web UI log
# viewer shows a unified picture. Falls back to console-only if the log
# directory doesn't exist yet (e.g. first boot before the LED service has run).
logger = logging.getLogger("bin-led-webui")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)
try:
    _file_handler = logging.FileHandler(LOG_FILE)
    _file_handler.setFormatter(_fmt)
    logger.addHandler(_file_handler)
except OSError:
    pass  # Log directory not present; console only until LED service creates it

# Keys that can be updated via PATCH /api/config
EDITABLE_CONFIG_KEYS = {"led_brightness", "check_interval_hours", "update_interval_weeks", "log_level", "reminder_start_hours_before", "reminder_end_hours_after"}

# Keep in sync with TEST_COLOUR_HEX in bin-led-webui/static/consts.js
# and the general palette in bin-led-reminder/constants.py.
TEST_COLOURS = {
    "blue":   (  0,   0, 255),
    "green":  (  0, 255,   0),
    "red":    (255,   0,   0),
    "white":  (255, 255, 255),
    "orange": (255, 165,   0),
    "purple": (128,   0, 128),
    "pink":   (255,  20, 147),
    "cyan":   (  0, 255, 255),
    "yellow": (255, 255,   0),
}


def _read_json(path: Path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _recalculate_days_until(date_str: str) -> int | None:
    """Parse a date string like 'Wed - 25 Mar 2026' and return days from today."""
    try:
        parsed = datetime.strptime(date_str, "%a - %d %b %Y").date()
        return (parsed - date.today()).days
    except ValueError:
        return None


def _hours_until(date_str: str) -> int | None:
    """Parse a date string like 'Wed - 25 Mar 2026' and return whole hours from now to midnight of that date."""
    try:
        parsed = datetime.strptime(date_str, "%a - %d %b %Y")
        delta = parsed - datetime.now()
        return max(0, int(delta.total_seconds() // 3600))
    except ValueError:
        return None


def _leds_active(collections: list) -> bool:
    """Derive whether LEDs should currently be active based on schedule logic.

    The reminder window is read from config (reminder_start_hours_before /
    reminder_end_hours_after) with the same defaults as the LED service.
    """
    cfg = _read_json(CONFIG_FILE) or {}
    start_h = cfg.get("reminder_start_hours_before", 24)
    end_h = cfg.get("reminder_end_hours_after", 1)

    now = datetime.now()
    for col in collections:
        if col.get("bin_type") == "Black Bag":
            continue
        try:
            col_date = datetime.strptime(col["date"], "%a - %d %b %Y").date()
        except (ValueError, KeyError):
            continue
        col_dt = datetime(col_date.year, col_date.month, col_date.day)
        window_start = col_dt - timedelta(hours=start_h)
        window_end = col_dt + timedelta(hours=end_h)
        if window_start <= now <= window_end:
            return True
    return False


def _run_systemctl(*args) -> tuple[bool, str]:
    """Run a systemctl command. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", *args],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0, result.stderr.strip() or result.stdout.strip()
    except FileNotFoundError:
        return True, "Dev mode: systemctl not available"
    except subprocess.TimeoutExpired:
        return False, "systemctl command timed out"


def _service_is_active() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "bin-led-reminder"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == "active"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# --- Endpoints ---

@app.get("/api/schedule")
def get_schedule():
    data = _read_json(SCHEDULE_FILE)
    if data is None:
        raise HTTPException(status_code=404, detail="Schedule file not found")
    # Recalculate days_until at request time and filter to upcoming only
    collections = []
    for col in data.get("collections", []):
        days = _recalculate_days_until(col["date"])
        if days is None or days < 0:
            continue
        collections.append({
            "date": col["date"],
            "bin_type": col["bin_type"],
            "day_of_week": col.get("day_of_week", ""),
            "days_until": days,
        })
    return {
        "metadata": data.get("metadata", {}),
        "collections": collections,
    }


@app.get("/api/status")
def get_status():
    schedule_data = _read_json(SCHEDULE_FILE)
    collections = schedule_data.get("collections", []) if schedule_data else []

    has_error = ERROR_FILE.exists()
    error_details = None
    if has_error:
        error_details = _read_json(ERROR_FILE)

    next_collection = None
    for col in collections:
        if col.get("bin_type") == "Black Bag":
            continue
        days = _recalculate_days_until(col["date"])
        if days is not None and days >= 0:
            next_collection = {
                "date": col["date"],
                "bin_type": col["bin_type"],
                "days_until": days,
                "hours_until": _hours_until(col["date"]),
            }
            break

    return {
        "led_service_running": _service_is_active(),
        "has_error": has_error,
        "error_details": error_details,
        "next_collection": next_collection,
        "leds_active": _leds_active(collections),
    }


@app.get("/api/config")
def get_config():
    data = _read_json(CONFIG_FILE)
    if data is None:
        raise HTTPException(status_code=404, detail="Config file not found")
    # Return only the fields the UI cares about (omit base_url, uprn)
    return {
        "uprn": data.get("uprn"),
        "update_interval_weeks": data.get("update_interval_weeks"),
        "check_interval_hours": data.get("check_interval_hours"),
        "led_brightness": data.get("led_brightness"),
        "log_level": data.get("log_level"),
        "reminder_start_hours_before": data.get("reminder_start_hours_before", 24),
        "reminder_end_hours_after": data.get("reminder_end_hours_after", 1),
    }


@app.patch("/api/config")
def patch_config(updates: dict):
    disallowed = set(updates.keys()) - EDITABLE_CONFIG_KEYS
    if disallowed:
        raise HTTPException(status_code=400, detail=f"Keys not editable: {disallowed}")

    if "led_brightness" in updates:
        v = updates["led_brightness"]
        if not isinstance(v, (int, float)) or not (0.0 <= v <= 1.0):
            raise HTTPException(status_code=400, detail="led_brightness must be between 0.0 and 1.0")

    data = _read_json(CONFIG_FILE)
    if data is None:
        raise HTTPException(status_code=404, detail="Config file not found")

    data.update(updates)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Web UI: config updated — %s", updates)
    return data


@app.get("/api/logs")
def get_logs(lines: int = 50):
    lines = min(lines, 200)
    if not LOG_FILE.exists():
        return {"lines": []}
    with open(LOG_FILE) as f:
        all_lines = f.readlines()
    return {"lines": [l.rstrip("\n") for l in all_lines[-lines:]]}


@app.post("/api/service/{action}")
def service_action(action: str):
    valid_actions = {"start", "stop", "restart", "clear-errors", "force-update"}
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}. Valid: {valid_actions}")

    if action == "clear-errors":
        if ERROR_FILE.exists():
            ERROR_FILE.unlink()
        success, msg = _run_systemctl("restart", "bin-led-reminder")
        if success:
            logger.info("Web UI: error state cleared and service restarted")
        else:
            logger.error("Web UI: clear-errors failed — %s", msg)
        return {"success": success, "action": action, "message": msg or "Error state cleared and service restarted"}

    if action == "force-update":
        if SCHEDULE_FILE.exists():
            SCHEDULE_FILE.unlink()
        logger.info("Web UI: LED service force-update requested")
        success, msg = _run_systemctl("restart", "bin-led-reminder")
        if success:
            logger.info("Web UI: LED service force-update succeeded")
        else:
            logger.error("Web UI: LED service force-update failed — %s", msg)
        return {"success": success, "action": action, "message": msg or "Schedule cleared and service restarted"}

    logger.info("Web UI: service %s requested", action)
    success, msg = _run_systemctl(action, "bin-led-reminder")
    if success:
        logger.info("Web UI: service %s succeeded", action)
    else:
        logger.error("Web UI: service %s failed — %s", action, msg)
    return {
        "success": success,
        "action": action,
        "message": msg or f"Service {action} successful",
    }


@app.post("/api/leds/test")
def test_leds(body: dict):
    # NOTE: This endpoint blocks for ~3 seconds while the LEDs are lit.
    # Acceptable for a single-user local tool.
    # If async becomes necessary in future: asyncio.sleep with run_in_executor.
    if not BLINKT_AVAILABLE:
        raise HTTPException(status_code=503, detail="blinkt not available in this environment")
    if _service_is_active():
        raise HTTPException(status_code=409, detail="LED service is running. Stop it before using test controls.")
    colour = body.get("colour", "")
    if colour not in TEST_COLOURS:
        raise HTTPException(status_code=400, detail=f"Unknown colour. Valid: {', '.join(TEST_COLOURS)}")
    config = _read_json(CONFIG_FILE) or {}
    brightness = config.get("led_brightness", 0.1)
    r, g, b = TEST_COLOURS[colour]
    logger.info("Web UI: LED test flash started — colour=%s brightness=%.2f", colour, brightness)
    blinkt.set_all(r, g, b, brightness)
    blinkt.show()
    time.sleep(3)
    blinkt.clear()
    blinkt.show()
    logger.info("Web UI: LED test flash complete — colour=%s", colour)
    return {"success": True, "colour": colour}


# Serve frontend
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
