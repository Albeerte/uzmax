"""
UzMAX — Unified Medical AI + Robot Control Server
===================================================
Single FastAPI server that combines:
  • Voice AI assistant  (Yandex STT/TTS + OpenRouter LLM)
  • Face recognition    (Gemini embeddings + Qdrant vector store)
  • ESP32 robot control (HAND / HEAD / MOVE via USB serial)

Protocol for ESP32_HAND  (new firmware):
    R 1 90       → right servo #1 to 90°
    L 6 120      → left servo #6 to 120°

Protocol for ESP32_HEAD:
    HEAD LEFT 40
    HEAD RIGHT 40
    HEAD STOP
    HEAD SERVO 90
    HEAD NEUTRAL 90
    HEAD LED 255 0 0
    HEAD LED_OFF
    HEAD RAINBOW

Protocol for ESP32_MOVE:
    MOVE FWD 150 / MOVE BACK 150 / MOVE LEFT 120 / MOVE RIGHT 120 / MOVE STOP

Run:
    python uzmax_server/main.py
    # or
    cd uzmax_server
    uvicorn main:app --host 0.0.0.0 --port 5000 --reload

.env keys needed:
    YANDEX_CATALOG_ID
    YANDEX_API_KEY
    OPENROUTER_API_KEY   (or OPENAI_API_KEY)
    GEMINI_API_KEY       (for face embeddings)
"""

import os
import re
import json
import base64
import asyncio
import logging
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime

import serial
import serial.tools.list_ports
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from agent.speech_to_text import YandexSpeechRecognizer, SttStreamingSession
from agent.text_to_speech import YandexStreamingSynthesizer, TtsStreamingSession
from agent.llm import OpenAIClient
from agent.face_encoder import FaceEncoder
from agent.face_store import FaceVectorStore

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

# ── MLX90640 Thermal Camera (optional — only works on RPi with I2C) ──
board = None
busio = None
adafruit_mlx90640 = None
_THERMAL_HW = False
_THERMAL_IMPORT_ERROR = None
THERMAL_INSTALL_COMMAND = (
    f"{sys.executable} -m pip install adafruit-circuitpython-mlx90640 adafruit-blinka"
)


def _try_import_thermal_hw() -> bool:
    global board, busio, adafruit_mlx90640, _THERMAL_HW, _THERMAL_IMPORT_ERROR

    if os.name == "nt":
        _THERMAL_HW = False
        _THERMAL_IMPORT_ERROR = "Windows does not provide direct I2C access for MLX90640."
        return False

    try:
        import board as board_module
        import busio as busio_module
        import adafruit_mlx90640 as mlx_module
        board = board_module
        busio = busio_module
        adafruit_mlx90640 = mlx_module
        _THERMAL_HW = True
        _THERMAL_IMPORT_ERROR = None
        return True
    except Exception as exc:
        _THERMAL_HW = False
        _THERMAL_IMPORT_ERROR = str(exc)
        return False


class ThermalCamera:
    """Wrapper for MLX90640 32×24 IR sensor. Gracefully disabled when not connected."""

    ROWS, COLS = 24, 32

    def __init__(self):
        self.enabled = False
        self._mlx    = None
        self._frame  = [0.0] * (self.ROWS * self.COLS)
        self._lock   = threading.Lock()
        self.reason  = "not_connected"
        self.message = "MLX90640 sensor is not connected."
        self.initialize()

    def initialize(self) -> bool:
        if self.enabled and self._mlx is not None:
            return True

        self.enabled = False
        self._mlx = None
        self.reason = "not_connected"
        self.message = "MLX90640 sensor is not connected."

        if not _try_import_thermal_hw():
            logger_pre = logging.getLogger(__name__)
            import_error = _THERMAL_IMPORT_ERROR or ""
            if "WINDOWS" in import_error.upper() or "UNABLE TO IDENTIFY THE BOARD" in import_error.upper():
                self.reason = "unsupported_platform"
                self.message = (
                    "MLX90640 is an I2C sensor. This Windows machine has no supported I2C board "
                    "for Blinka. Run the server on the Raspberry Pi wired to the sensor, or use a "
                    "supported USB-I2C bridge such as FT232H."
                )
            else:
                self.reason = "missing_dependencies"
                self.message = (
                    "Python thermal libraries are missing in the server Python environment. "
                    "Run the install command below on the Raspberry Pi, using the same Python "
                    "that starts uzmax_server/main.py, then press Thermal ON again."
                )
            logger_pre.info("[THERMAL] local I2C unavailable: %s", _THERMAL_IMPORT_ERROR)
            return False

        try:
            i2c = busio.I2C(board.SCL, board.SDA, frequency=100_000)
            self._mlx = adafruit_mlx90640.MLX90640(i2c)
            self._mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_2_HZ
            self.enabled = True
            self.reason = None
            self.message = "MLX90640 ready."
            logging.getLogger(__name__).info("[THERMAL] MLX90640 ready (2 Hz)")
            return True
        except Exception as exc:
            self.reason = "init_failed"
            self.message = str(exc)
            logging.getLogger(__name__).warning("[THERMAL] MLX90640 init failed: %s", exc)
            return False

    def read(self) -> dict:
        """Read one 32×24 frame. Returns dict with stats + flat list."""
        if not self.enabled or self._mlx is None:
            return {
                "ok": False,
                "reason": self.reason or "not_connected",
                "message": self.message,
                "install": THERMAL_INSTALL_COMMAND,
            }
        try:
            with self._lock:
                self._mlx.getFrame(self._frame)
            arr   = np.array(self._frame, dtype=np.float32).reshape((self.ROWS, self.COLS))
            return {
                "ok":     True,
                "frame":  arr.flatten().tolist(),   # 768 float values
                "rows":   self.ROWS,
                "cols":   self.COLS,
                "max":    round(float(arr.max()),  1),
                "min":    round(float(arr.min()),  1),
                "avg":    round(float(arr.mean()), 1),
                "center": round(float(arr[self.ROWS//2, self.COLS//2]), 1),
            }
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}


_thermal = ThermalCamera()
_remote_thermal = {"data": None, "updated_at": 0.0, "source": None}
_thermal_runtime = {"enabled": False, "updated_at": 0.0}
REMOTE_THERMAL_TTL_SECONDS = 8.0
HAND_SERVO_LIMITS = {
    "R": {
        1: (90, 180),
        2: (0, 180),
        3: (90, 180),
        4: (0, 180),
        5: (0, 180),
        6: (0, 180),
    },
    "L": {
        1: (0, 180),
        2: (0, 180),
        3: (0, 180),
        4: (0, 180),
        5: (0, 180),
        6: (0, 180),
    },
}


def _normalize_thermal_payload(payload: dict, source: str = "raspberry_pi") -> dict:
    frame = payload.get("frame")
    expected = ThermalCamera.ROWS * ThermalCamera.COLS
    if not isinstance(frame, list) or len(frame) != expected:
        raise ValueError(f"frame must contain {expected} temperature values")

    arr = np.array(frame, dtype=np.float32).reshape((ThermalCamera.ROWS, ThermalCamera.COLS))
    center_default = arr[ThermalCamera.ROWS // 2, ThermalCamera.COLS // 2]
    return {
        "ok": True,
        "source": source,
        "frame": arr.flatten().round(2).tolist(),
        "rows": ThermalCamera.ROWS,
        "cols": ThermalCamera.COLS,
        "max": round(float(payload.get("max", arr.max())), 1),
        "min": round(float(payload.get("min", arr.min())), 1),
        "avg": round(float(payload.get("avg", arr.mean())), 1),
        "center": round(float(payload.get("center", center_default)), 1),
        "timestamp": time.time(),
    }


def _read_thermal_source() -> dict:
    if not _thermal_runtime.get("enabled"):
        return {
            "ok": False,
            "reason": "disabled",
            "message": "Thermal camera is off. Turn it on from the dashboard.",
            "enabled": False,
        }

    local = _thermal.read()
    if local.get("ok"):
        local["source"] = "local_i2c"
        local["enabled"] = True
        return local

    remote = _remote_thermal.get("data")
    remote_age = time.time() - float(_remote_thermal.get("updated_at") or 0)
    if remote and remote_age <= REMOTE_THERMAL_TTL_SECONDS:
        data = dict(remote)
        data["source"] = _remote_thermal.get("source") or data.get("source") or "raspberry_pi"
        data["remote_age"] = round(remote_age, 2)
        data["enabled"] = True
        return data

    data = dict(local)
    data["enabled"] = True
    if remote:
        data["remote_reason"] = "stale"
        data["remote_age"] = round(remote_age, 2)
        data["message"] = (
            "Remote thermal agent is not sending fresh frames. Start the Raspberry Pi thermal "
            "agent and point it at this server link."
        )
    return data


def _set_thermal_enabled(enabled: bool) -> dict:
    if enabled:
        _thermal.initialize()

    _thermal_runtime["enabled"] = bool(enabled)
    _thermal_runtime["updated_at"] = time.time()
    return {
        "ok": True,
        "enabled": _thermal_runtime["enabled"],
        "hardware_ready": bool(_thermal.enabled),
        "reason": None if _thermal.enabled else _thermal.reason,
        "message": _thermal.message,
        "install": None if _thermal.enabled else THERMAL_INSTALL_COMMAND,
    }

# ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

def configured_secret(value: str | None) -> str | None:
    if not value:
        return None
    upper = value.upper()
    if any(marker in upper for marker in ("YOUR_", "YOUR-", "YOUR", "_HERE", "KEY_HERE")):
        return None
    return value


FOLDER_ID            = configured_secret(os.getenv("YANDEX_CATALOG_ID"))
API_KEY              = configured_secret(os.getenv("YANDEX_API_KEY"))
GEMINI_API_KEY       = configured_secret(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.62"))
FACE_LOG_ALL         = os.getenv("FACE_LOG_ALL_COMPARISONS", "false").lower() == "true"
ENV_PATH             = Path(".env")

SETTINGS_KEYS = [
    "YANDEX_API_KEY",
    "YANDEX_CATALOG_ID",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "GEMINI_API_KEY",
    "FACE_MATCH_THRESHOLD",
    "OPENROUTER_APP_NAME",
    "OPENROUTER_SITE_URL",
    "ARDUINO_CLI_PATH",
    "ESP32_FQBN",
]


def read_env_values() -> dict:
    values = {key: os.getenv(key, "") for key in SETTINGS_KEYS}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in SETTINGS_KEYS:
                values[key] = value.strip().strip('"').strip("'")
    return values


def write_env_values(new_values: dict) -> None:
    existing = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    output = []

    for raw in existing:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            output.append(raw)
            continue
        key = raw.split("=", 1)[0].strip()
        if key in SETTINGS_KEYS:
            output.append(f"{key}={str(new_values.get(key, '')).strip()}")
            seen.add(key)
        else:
            output.append(raw)

    if output and output[-1].strip():
        output.append("")
    for key in SETTINGS_KEYS:
        if key not in seen:
            output.append(f"{key}={str(new_values.get(key, '')).strip()}")

    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not GEMINI_API_KEY:
        logger.info("Face bootstrap skipped: GEMINI_API_KEY is not configured")
    else:
        try:
            load_registered_faces()
        except Exception as exc:
            logger.warning("Face bootstrap skipped: %s", exc)
    yield


app = FastAPI(title="UzMAX Unified Server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static", exist_ok=True)
os.makedirs("images", exist_ok=True)
REGISTER_FACES_DIR  = Path("data/register_faces")
REGISTER_FACES_DIR.mkdir(parents=True, exist_ok=True)
REGISTER_FACES_JSON = REGISTER_FACES_DIR / "registry.json"
IMAGES_DIR          = Path("images")
PROJECT_ROOT        = Path(__file__).resolve().parent.parent
ARDUINO_CLI_DEFAULT = Path(r"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe")
ESP32_FQBN_DEFAULT  = os.getenv("ESP32_FQBN", "esp32:esp32:esp32")

FIRMWARE_SKETCHES = {
    "hand": PROJECT_ROOT / "hand" / "hand.ino",
    "head": PROJECT_ROOT / "head" / "head.ino",
    "move": PROJECT_ROOT / "movements" / "move.ino",
}
FIRMWARE_VERSION_DIR = PROJECT_ROOT / "firmware_versions"

app.mount("/static", StaticFiles(directory="static"), name="static")

face_store = None
face_encoder = None


# ═══════════════════════════════════════════════════════════════════
#  ESP32 SERIAL MANAGER
# ═══════════════════════════════════════════════════════════════════

SERIAL_BAUD = 115200

_devices: dict[str, dict] = {
    "hand": {"ser": None, "port": None, "lock": threading.Lock()},
    "head": {"ser": None, "port": None, "lock": threading.Lock()},
    "move": {"ser": None, "port": None, "lock": threading.Lock()},
}


def _serial_error_message(port: str, exc: Exception) -> str:
    raw = str(exc)
    if "Access is denied" in raw or "PermissionError" in raw:
        return (
            f"{port} is busy. Close Arduino IDE Serial Monitor/Plotter, PuTTY, "
            "PlatformIO monitor, or any other serial app, then retry Auto Connect."
        )
    return raw


def _serial_port_owner(port: str, exclude_device: str | None = None) -> str | None:
    for name, dev in _devices.items():
        if name == exclude_device:
            continue
        ser = dev.get("ser")
        if dev.get("port") == port and ser is not None and ser.is_open:
            return name
    return None


def _serial_connect(device: str, port: str) -> dict:
    owner = _serial_port_owner(port, exclude_device=device)
    if owner:
        return {
            "ok": False,
            "message": f"{port} is already connected as {owner.upper()}. Disconnect it first.",
        }

    dev = _devices[device]
    with dev["lock"]:
        if dev["ser"] and dev["ser"].is_open:
            try:
                dev["ser"].close()
            except Exception:
                pass
        try:
            dev["ser"]  = serial.Serial(port, SERIAL_BAUD, timeout=1)
            dev["port"] = port
            time.sleep(2)
            logger.info("[SERIAL] %s connected → %s", device.upper(), port)
            return {"ok": True, "message": f"Connected to {port}"}
        except Exception as e:
            dev["ser"]  = None
            dev["port"] = None
            message = _serial_error_message(port, e)
            logger.error("[SERIAL] %s failed on %s: %s", device.upper(), port, message)
            return {"ok": False, "message": message}


def _serial_auto_connect() -> dict:
    """Scan serial ports, PING each board, and keep HAND/HEAD/MOVE matches open."""
    found: dict[str, dict] = {}
    errors: list[dict] = []

    for device in _devices:
        _serial_disconnect(device)

    for port_info in serial.tools.list_ports.comports():
        port_name = port_info.device
        ser = None
        try:
            ser = serial.Serial(port_name, SERIAL_BAUD, timeout=1)
            time.sleep(2)
            ser.write(b"PING\n")
            time.sleep(0.35)

            lines = []
            while ser.in_waiting:
                line = ser.readline().decode(errors="ignore").strip()
                if line:
                    lines.append(line)
            response = "\n".join(lines)

            matched = None
            for device_name in ("HAND", "HEAD", "MOVE"):
                if f"DEVICE:{device_name}" in response:
                    matched = device_name.lower()
                    break

            # Legacy hand sketches sometimes print only this banner and support
            # R/L servo commands, but do not identify as DEVICE:HAND.
            if not matched:
                legacy_hand_markers = (
                    "ESP32 12 SERVO CONTROL READY",
                    "USE: R 1 90",
                    "USE: L 6 0",
                    "ERROR FORMAT MUST BE: R 1 90",
                )
                if any(marker in response.upper() for marker in legacy_hand_markers):
                    matched = "hand"

            if not matched:
                legacy_head_markers = (
                    "DEVICE:HEAD",
                    "HEAD READY",
                    "LED SYSTEM READY",
                    "SERVO TEST READY",
                    "SEND ANGLE: 0 TO 180",
                    "COMMANDS:",
                    "RED, GREEN, BLUE, WHITE, OFF",
                )
                if any(marker in response.upper() for marker in legacy_head_markers):
                    matched = "head"

            if not matched:
                ser.close()
                continue

            dev = _devices[matched]
            with dev["lock"]:
                if dev["ser"] and dev["ser"].is_open:
                    dev["ser"].close()
                dev["ser"] = ser
                dev["port"] = port_name
            found[matched] = {
                "port": port_name,
                "description": port_info.description,
                "response": response,
            }
            logger.info("[SERIAL] Auto-connected %s on %s", matched.upper(), port_name)

        except Exception as exc:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
            errors.append({"port": port_name, "message": _serial_error_message(port_name, exc)})

    return {
        "ok": True,
        "found": found,
        "errors": errors,
        "status": {k: _serial_status(k) for k in _devices},
    }


def _serial_send(device: str, command: str) -> tuple[bool, str]:
    dev  = _devices[device]
    with dev["lock"]:
        ser = dev["ser"]
        if ser is None or not ser.is_open:
            return False, "Not connected"
        try:
            ser.write((command + "\n").encode("utf-8"))
            time.sleep(0.08)
            resp = ""
            while ser.in_waiting:
                resp += ser.readline().decode(errors="ignore").strip() + "\n"
            response = resp.strip() or "OK:NO_RESPONSE"
            response_upper = response.upper()
            accepted = not any(token in response_upper for token in ("ERR", "ERROR", "UNKNOWN"))
            return accepted, response
        except serial.SerialException as exc:
            logger.error("[SERIAL] %s lost: %s", device.upper(), exc)
            dev["ser"] = None
            return False, str(exc)


def _legacy_head_led_command(command: str) -> str | None:
    parts = command.strip().split()
    upper = [part.upper() for part in parts]
    if len(parts) == 5 and upper[:2] == ["HEAD", "LED"]:
        return f"color {parts[2]} {parts[3]} {parts[4]}"
    if upper == ["HEAD", "LED_OFF"]:
        return "off"
    if upper == ["HEAD", "RAINBOW"]:
        return "rainbow"
    if len(parts) == 3 and upper[:2] == ["HEAD", "BRIGHTNESS"]:
        return f"brightness {parts[2]}"
    return None


def _normalize_head_command(command: str) -> str:
    parts = command.strip().split()
    upper = [part.upper() for part in parts]
    if len(parts) == 4 and upper[:2] == ["HEAD", "SERVO"]:
        # Old dashboard format was HEAD SERVO <servo_num> <angle>.
        # Current HEAD firmware has one continuous/raw servo: HEAD SERVO <value>.
        return f"HEAD SERVO {parts[3]}"
    return command


def _serial_disconnect(device: str):
    dev = _devices[device]
    with dev["lock"]:
        if dev["ser"] and dev["ser"].is_open:
            dev["ser"].close()
        dev["ser"]  = None
        dev["port"] = None


def _serial_status(device: str) -> dict:
    dev       = _devices[device]
    connected = dev["ser"] is not None and dev["ser"].is_open
    return {"connected": connected, "port": dev["port"]}


def _arduino_cli_path() -> str | None:
    configured = os.getenv("ARDUINO_CLI_PATH", "").strip()
    candidates = [
        configured,
        shutil.which("arduino-cli"),
        str(ARDUINO_CLI_DEFAULT) if ARDUINO_CLI_DEFAULT.exists() else "",
    ]
    return next((path for path in candidates if path and Path(path).exists()), None)


def _run_arduino_command(args: list[str], timeout: int = 180) -> dict:
    cli = _arduino_cli_path()
    if not cli:
        return {
            "ok": False,
            "message": "arduino-cli not found. Install Arduino IDE or set ARDUINO_CLI_PATH in .env.",
            "stdout": "",
            "stderr": "",
        }

    cli_tmp = PROJECT_ROOT / "firmware_tmp" / "cli_tmp"
    cli_tmp.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TMP"] = str(cli_tmp)
    env["TEMP"] = str(cli_tmp)
    env["TMPDIR"] = str(cli_tmp)

    proc = subprocess.run(
        [cli, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "command": " ".join([cli, *args]),
    }


def _firmware_compile_upload(target: str, port: str, code: str, fqbn: str, compile_only: bool) -> dict:
    sketch_name = f"UZMAX_{target.upper()}_WEB"
    temp_root = PROJECT_ROOT / "firmware_tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    run_dir = temp_root / f"uzmax_firmware_{target}_{int(time.time() * 1000)}"
    sketch_dir = run_dir / sketch_name
    build_dir = run_dir / "build"
    sketch_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    (sketch_dir / f"{sketch_name}.ino").write_text(code, encoding="utf-8")

    compile_result = _run_arduino_command([
        "compile",
        "--fqbn", fqbn,
        "--build-path", str(build_dir),
        str(sketch_dir),
    ])
    compile_result["workdir"] = str(sketch_dir)
    compile_result["build_dir"] = str(build_dir)
    if compile_only or not compile_result["ok"]:
        return {"ok": compile_result["ok"], "stage": "compile", **compile_result}

    if target in _devices and _serial_status(target).get("port") == port:
        _serial_disconnect(target)

    upload_result = _run_arduino_command(
        [
            "upload",
            "-p", port,
            "--fqbn", fqbn,
            "--input-dir", str(build_dir),
            str(sketch_dir),
        ],
        timeout=240,
    )
    upload_result["workdir"] = str(sketch_dir)
    return {
        "ok": upload_result["ok"],
        "stage": "upload",
        "compile": compile_result,
        **upload_result,
    }


def _firmware_assert_target(target: str) -> str:
    target = str(target or "").lower().strip()
    if target not in FIRMWARE_SKETCHES:
        raise ValueError("Unknown firmware target")
    return target


def _firmware_version_path(target: str) -> Path:
    target = _firmware_assert_target(target)
    return FIRMWARE_VERSION_DIR / f"{target}.json"


def _firmware_read_versions(target: str) -> list[dict]:
    path = _firmware_version_path(target)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        versions = data if isinstance(data, list) else data.get("versions", [])
        return versions if isinstance(versions, list) else []
    except Exception:
        logging.exception("Could not read firmware versions: %s", path)
        return []


def _firmware_write_versions(target: str, versions: list[dict]) -> None:
    path = _firmware_version_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(versions, ensure_ascii=False, indent=2), encoding="utf-8")


def _firmware_canonical_code(target: str) -> str:
    target = _firmware_assert_target(target)
    path = FIRMWARE_SKETCHES[target]
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _firmware_find_version(target: str, version_id: str) -> dict | None:
    for item in _firmware_read_versions(target):
        if str(item.get("id")) == str(version_id):
            return item
    return None


def _firmware_filename(target: str, version: dict | None = None) -> str:
    target = _firmware_assert_target(target)
    suffix = "latest"
    if version:
        suffix = re.sub(r"[^A-Za-z0-9_-]+", "_", str(version.get("name") or version.get("id") or "saved")).strip("_")[:40] or "saved"
    return f"UZMAX_{target.upper()}_{suffix}.ino"


# ═══════════════════════════════════════════════════════════════════
#  ROBOT CONTROL REST ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/ports")
def list_ports():
    return JSONResponse([
        {"device": p.device, "description": p.description}
        for p in serial.tools.list_ports.comports()
    ])


@app.post("/api/connect")
async def connect_device(payload: dict):
    device = payload.get("device", "").lower()
    port   = payload.get("port", "")
    if device not in _devices:
        return JSONResponse({"ok": False, "message": "Unknown device"}, status_code=400)
    if not port:
        return JSONResponse({"ok": False, "message": "No port specified"}, status_code=400)
    result = await asyncio.to_thread(_serial_connect, device, port)
    return JSONResponse(result)


@app.post("/api/auto-connect")
async def auto_connect_devices():
    result = await asyncio.to_thread(_serial_auto_connect)
    return JSONResponse(result)


@app.post("/api/disconnect")
async def disconnect_device(payload: dict):
    device = payload.get("device", "").lower()
    if device not in _devices:
        return JSONResponse({"ok": False, "message": "Unknown device"}, status_code=400)
    await asyncio.to_thread(_serial_disconnect, device)
    return JSONResponse({"ok": True})


@app.get("/api/robot/status")
def robot_status():
    return JSONResponse({k: _serial_status(k) for k in _devices})


@app.get("/api/firmware/sketches")
def firmware_sketches():
    sketches = {}
    for target, path in FIRMWARE_SKETCHES.items():
        exists = path.exists()
        versions = _firmware_read_versions(target)
        latest = versions[0] if versions else None
        canonical_code = path.read_text(encoding="utf-8") if exists else ""
        sketches[target] = {
            "target": target,
            "path": str(path),
            "exists": exists,
            "code": latest.get("code", "") if latest else canonical_code,
            "canonical_code": canonical_code,
            "latest_version": latest,
            "version_count": len(versions),
        }
    return JSONResponse({
        "ok": True,
        "arduino_cli": _arduino_cli_path(),
        "default_fqbn": ESP32_FQBN_DEFAULT,
        "sketches": sketches,
    })


@app.get("/api/firmware/versions")
def firmware_versions(target: str = "move"):
    try:
        target = _firmware_assert_target(target)
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    versions = _firmware_read_versions(target)
    return JSONResponse({
        "ok": True,
        "target": target,
        "versions": versions,
        "canonical_code": _firmware_canonical_code(target),
    })


@app.post("/api/firmware/versions")
async def firmware_save_version(payload: dict):
    try:
        target = _firmware_assert_target(payload.get("target", "move"))
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

    code = str(payload.get("code", "")).strip()
    if not code:
        return JSONResponse({"ok": False, "message": "Firmware code is empty"}, status_code=400)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    version_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = str(payload.get("name", "")).strip() or f"{target.upper()} {now}"
    fqbn = str(payload.get("fqbn", ESP32_FQBN_DEFAULT)).strip() or ESP32_FQBN_DEFAULT
    notes = str(payload.get("notes", "")).strip()
    item = {
        "id": version_id,
        "target": target,
        "name": name,
        "created_at": now,
        "fqbn": fqbn,
        "notes": notes,
        "code": code,
    }
    versions = _firmware_read_versions(target)
    versions.insert(0, item)
    _firmware_write_versions(target, versions[:200])
    return JSONResponse({"ok": True, "target": target, "version": item, "versions": versions[:200]})


@app.get("/api/firmware/download")
def firmware_download(target: str = "move", version_id: str = "latest"):
    try:
        target = _firmware_assert_target(target)
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

    version = None
    code = ""
    if version_id == "canonical":
        code = _firmware_canonical_code(target)
    else:
        versions = _firmware_read_versions(target)
        if version_id and version_id != "latest":
            version = _firmware_find_version(target, version_id)
        elif versions:
            version = versions[0]
        code = version.get("code", "") if version else _firmware_canonical_code(target)

    if not code.strip():
        return JSONResponse({"ok": False, "message": "Firmware code is empty"}, status_code=404)

    return Response(
        content=code,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_firmware_filename(target, version)}"'},
    )


@app.post("/api/firmware/compile")
async def firmware_compile(payload: dict):
    target = str(payload.get("target", "move")).lower()
    code = str(payload.get("code", "")).strip()
    fqbn = str(payload.get("fqbn", ESP32_FQBN_DEFAULT)).strip() or ESP32_FQBN_DEFAULT
    if target not in FIRMWARE_SKETCHES:
        return JSONResponse({"ok": False, "message": "Unknown firmware target"}, status_code=400)
    if not code:
        return JSONResponse({"ok": False, "message": "Firmware code is empty"}, status_code=400)
    result = await asyncio.to_thread(_firmware_compile_upload, target, "", code, fqbn, True)
    return JSONResponse(result)


@app.post("/api/firmware/upload")
async def firmware_upload(payload: dict):
    target = str(payload.get("target", "move")).lower()
    port = str(payload.get("port", "")).strip()
    code = str(payload.get("code", "")).strip()
    fqbn = str(payload.get("fqbn", ESP32_FQBN_DEFAULT)).strip() or ESP32_FQBN_DEFAULT
    if target not in FIRMWARE_SKETCHES:
        return JSONResponse({"ok": False, "message": "Unknown firmware target"}, status_code=400)
    if not port:
        return JSONResponse({"ok": False, "message": "Select a COM port before upload"}, status_code=400)
    if not code:
        return JSONResponse({"ok": False, "message": "Firmware code is empty"}, status_code=400)
    result = await asyncio.to_thread(_firmware_compile_upload, target, port, code, fqbn, False)
    return JSONResponse(result)


@app.post("/api/hand/move")
async def hand_move(payload: dict):
    """
    New firmware protocol: R 1 90  /  L 6 120
    Payload: {hand: 'R'|'L', servo: 1-6, angle: 0-180}
    """
    try:
        hand = str(payload.get("hand", "R")).upper()
        servo = int(payload.get("servo", 1))
        angle = max(0, min(180, int(payload.get("angle", 90))))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "message": "Servo and angle must be numbers"}, status_code=400)

    if hand not in ("R", "L") or not (1 <= servo <= 6):
        return JSONResponse({"ok": False, "message": "Invalid hand or servo"}, status_code=400)

    min_angle, max_angle = HAND_SERVO_LIMITS[hand][servo]
    angle = max(min_angle, min(max_angle, angle))

    cmd = f"{hand} {servo} {angle}"
    ok, resp = await asyncio.to_thread(_serial_send, "hand", cmd)
    return JSONResponse({"ok": ok, "sent": cmd, "response": resp,
                         "connected": _serial_status("hand")["connected"]})


@app.post("/api/head/command")
async def head_command(payload: dict):
    """
    HEAD LEFT 40 / HEAD RIGHT 40 / HEAD STOP / HEAD SERVO 90
    HEAD LED r g b / HEAD LED_OFF / HEAD RAINBOW
    Payload: {command: '...'}
    """
    requested = str(payload.get("command", "")).strip()
    if not requested:
        return JSONResponse({"ok": False, "message": "Empty command"}, status_code=400)
    cmd = _normalize_head_command(requested)
    ok, resp = await asyncio.to_thread(_serial_send, "head", cmd)
    fallback = _legacy_head_led_command(cmd)
    if fallback and (not ok or "UNKNOWN" in resp.upper()):
        ok, resp = await asyncio.to_thread(_serial_send, "head", fallback)
        return JSONResponse({
            "ok": ok,
            "sent": fallback,
            "requested": cmd,
            "response": resp,
            "fallback": True,
            "connected": _serial_status("head")["connected"],
        })
    return JSONResponse({"ok": ok, "sent": cmd, "response": resp,
                         "requested": requested if requested != cmd else None,
                         "connected": _serial_status("head")["connected"]})


@app.post("/api/move/command")
async def move_command(payload: dict):
    """
    MOVE FWD 150 / MOVE BACK 150 / MOVE LEFT 120 / MOVE RIGHT 120 / MOVE STOP
    Payload: {command: '...'}
    """
    cmd = str(payload.get("command", "")).strip().upper()
    if not cmd:
        return JSONResponse({"ok": False, "message": "Empty command"}, status_code=400)
    ok, resp = await asyncio.to_thread(_serial_send, "move", cmd)
    return JSONResponse({"ok": ok, "sent": cmd, "response": resp,
                         "connected": _serial_status("move")["connected"]})


@app.post("/api/raw")
async def raw_command(payload: dict):
    """Send any raw command to any device."""
    device  = str(payload.get("device", "hand")).lower()
    command = str(payload.get("command", "")).strip()
    if device not in _devices or not command:
        return JSONResponse({"ok": False, "message": "Bad device or empty command"}, status_code=400)
    ok, resp = await asyncio.to_thread(_serial_send, device, command)
    return JSONResponse({"ok": ok, "sent": command, "response": resp})


@app.get("/api/settings")
async def get_settings():
    """Return editable local runtime settings from uzmax_server/.env."""
    return JSONResponse({
        "ok": True,
        "path": str(ENV_PATH.resolve()),
        "settings": read_env_values(),
    })


@app.post("/api/settings")
async def save_settings(payload: dict):
    """Persist dashboard settings to .env and refresh in-process config."""
    global FOLDER_ID, API_KEY, GEMINI_API_KEY, FACE_MATCH_THRESHOLD
    global face_encoder, face_store

    incoming = payload.get("settings", payload)
    if not isinstance(incoming, dict):
        return JSONResponse({"ok": False, "message": "settings must be an object"}, status_code=400)

    values = read_env_values()
    for key in SETTINGS_KEYS:
        if key in incoming:
            values[key] = str(incoming.get(key, "") or "").strip()

    try:
        threshold = float(values.get("FACE_MATCH_THRESHOLD") or "0.62")
    except ValueError:
        return JSONResponse({"ok": False, "message": "FACE_MATCH_THRESHOLD must be a number"}, status_code=400)

    write_env_values(values)

    for key, value in values.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)

    FOLDER_ID = configured_secret(values.get("YANDEX_CATALOG_ID"))
    API_KEY = configured_secret(values.get("YANDEX_API_KEY"))
    GEMINI_API_KEY = configured_secret(values.get("GEMINI_API_KEY"))
    FACE_MATCH_THRESHOLD = threshold

    # These helpers read environment config when created, so recreate lazily.
    face_encoder = None
    face_store = None

    return JSONResponse({
        "ok": True,
        "path": str(ENV_PATH.resolve()),
        "settings": values,
    })


# ═══════════════════════════════════════════════════════════════════
#  FACE RECOGNITION HELPERS
# ═══════════════════════════════════════════════════════════════════

def get_face_encoder() -> FaceEncoder:
    global face_encoder
    if face_encoder is None:
        face_encoder = FaceEncoder()
    return face_encoder


def get_face_store() -> FaceVectorStore:
    global face_store
    if face_store is None:
        face_store = FaceVectorStore()
    return face_store


def save_base64_image(image_data: str) -> str:
    if "," in image_data:
        _, image_data = image_data.split(",", 1)
    image_bytes = base64.b64decode(image_data)
    ts           = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    filename     = IMAGES_DIR / f"face_{ts}.jpg"
    filename.write_bytes(image_bytes)
    return str(filename)


def load_registered_faces() -> tuple[int, int]:
    if not REGISTER_FACES_JSON.exists():
        return 0, 0
    try:
        data = json.loads(REGISTER_FACES_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to read registry: %s", exc)
        return 0, 0

    items   = data.get("faces", []) if isinstance(data, dict) else []
    loaded  = 0
    skipped = 0

    for item in items:
        file_name  = item.get("file")
        person_id  = item.get("person_id")
        first_name = item.get("first_name", "")
        last_name  = item.get("last_name", "")
        metadata   = item.get("metadata", {})

        if not file_name or not first_name:
            skipped += 1
            continue

        image_path = (REGISTER_FACES_DIR / file_name).resolve()
        if not image_path.exists():
            skipped += 1
            continue

        store = get_face_store()
        existing = store.get_person(person_id) if person_id else None
        if existing:
            store.add_snapshot(person_id, str(image_path))
            loaded += 1
            continue

        try:
            embedding = get_face_encoder().extract_embedding_from_path(str(image_path))
            store.register(
                embedding=embedding,
                first_name=first_name,
                last_name=last_name,
                snapshot_path=str(image_path),
                metadata=metadata,
                person_id=person_id,
            )
            loaded += 1
        except Exception as exc:
            logger.error("Bootstrap face %s: %s", file_name, exc)
            skipped += 1

    logger.info("Face bootstrap done: loaded=%s skipped=%s", loaded, skipped)
    return loaded, skipped


# ═══════════════════════════════════════════════════════════════════
#  FACE API
# ═══════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


@app.post("/api/faces")
async def save_face_snapshot(payload: dict):
    image_data = payload.get("image")
    if not image_data:
        return JSONResponse({"ok": False, "error": "image is required"}, status_code=400)
    try:
        filename = save_base64_image(image_data)
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid image"}, status_code=400)
    return JSONResponse({"ok": True, "path": filename})


@app.post("/api/faces/identify")
async def identify_faces(payload: dict):
    faces   = payload.get("faces", [])
    results = []

    for face in faces:
        image_data = face.get("image")
        if not image_data:
            continue
        try:
            snapshot_path = save_base64_image(image_data)
            embedding     = get_face_encoder().extract_embedding_from_base64(image_data)
        except Exception:
            continue

        store = get_face_store()
        match = store.identify(embedding, threshold=FACE_MATCH_THRESHOLD)

        if match:
            comps = match.get("comparisons", [])
            for c in (comps if FACE_LOG_ALL else comps[:3]):
                logger.info("Face compare: threshold=%.2f id=%s name=%s score=%.4f",
                            FACE_MATCH_THRESHOLD, c.get("person_id"),
                            c.get("full_name"), c.get("score", 0.0))
            logger.info("Face best: matched=%s score=%.4f name=%s",
                        match.get("matched"), match.get("score", 0.0), match.get("full_name"))

        if match and match.get("matched"):
            store.add_snapshot(match["person_id"], snapshot_path)
            results.append({"status": "known", "snapshot_path": snapshot_path, "person": match})
        else:
            results.append({"status": "unknown", "snapshot_path": snapshot_path, "embedding": embedding})

    return JSONResponse({"faces": results})


# ═══════════════════════════════════════════════════════════════════
#  VOICE AI WEBSOCKET
# ═══════════════════════════════════════════════════════════════════

def flush_sentence_buffer(buf: str) -> tuple[str | None, str]:
    m = re.search(r'[.!?…\n]\s', buf)
    if m:
        split_pos = m.end()
        return buf[:split_pos].strip(), buf[split_pos:]
    if len(buf) > 150:
        last_space = buf.rfind(' ', 0, 150)
        if last_space > 30:
            return buf[:last_space].strip(), buf[last_space:]
        return buf.strip(), ""
    return None, buf


def build_system_prompt(current_person: dict | None, onboarding: bool, current_lang: str) -> str:
    if current_lang == "uz-UZ":
        lang_instr = "Faqat o'zbek tilida, lotin yozuvida gapiring. Tabiiy, sodda, og'zaki va hurmatli bo'ling."
    elif current_lang == "en-US":
        lang_instr = "Speak only in English. Keep it natural, simple, spoken, and respectful."
    else:
        lang_instr = "Speak only in Russian. Keep it natural, simple, spoken, and respectful."

    base = (
        "Siz UzMAX robotining tibbiy yordamchi chatbotisiz. "
        "Loyiha: 'Yuqumli kasalliklar shifoxonasi uchun aqlli robot yaratish'. "
        "Rahbar: TATU, Azimov Bunyod Raximjonovich. "
        "Javoblar juda qisqa, jonli, do'stona va aniq bo'lsin. "
        "Odatda 1-2 qisqa gapdan oshmang. "
        "Tibbiy javoblarda bu dastlabki skrining ekanini eslating va zarur bo'lsa shifokorga murojaat qilishni ayting. "
        "Savol bersangiz, faqat bitta oddiy savol bering. "
        "Mehmonga hurmat bilan murojaat qiling. "
        f"{lang_instr}"
    )

    if onboarding:
        return base + " Yangi odam bilan tanishyapsiz. Qisqa tanishing va ism-familiyasini so'rang."

    if current_person:
        full_name = f'{current_person.get("first_name", "")} {current_person.get("last_name", "")}'.strip()
        metadata  = current_person.get("metadata") or {}
        meta_ctx  = f" Qo'shimcha ma'lumot: {json.dumps(metadata, ensure_ascii=False)}." if metadata else ""
        return (
            base
            + f" Siz bu odamni taniysiz: {full_name}. Iliq salomlashing."
            + meta_ctx
        )

    return base


def local_medical_fallback(user_text: str, current_person=None) -> str:
    """Short offline fallback when the configured LLM provider is unavailable."""
    q = (user_text or "").lower()
    name = ""
    if current_person:
        first = (current_person.get("first_name") or "").strip()
        if first:
            name = f"{first}, "

    if any(word in q for word in ("salom", "assalomu", "hello", "hi")):
        return f"{name}assalomu alaykum. Men UzMAX tibbiy yordamchiman. Sizga qanday yordam kerak?"
    if any(word in q for word in ("harorat", "temperatura", "isitma", "fever")):
        return f"{name}harorat skrining natijasidir. Agar isitma, holsizlik yoki og'riq bo'lsa, shifokorga murojaat qiling."
    if any(word in q for word in ("yo'tal", "yotal", "cough", "tomoq", "gripp")):
        return f"{name}yo'tal yoki tomoq og'rig'i bo'lsa, niqob taqing, suyuqlik iching va shifokor ko'rigidan o'ting."
    if any(word in q for word in ("doktor", "shifokor", "navbat", "qabul")):
        return f"{name}qaysi shifokorga yozilmoqchisiz: terapevt, kardiolog yoki nevropatolog?"
    return f"{name}hozir cloud AI kaliti ishlamayapti, lekin men lokal rejimdaman. Savolingizni qisqaroq yozing."


@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WS /ws/chat connected")

    recognizer  = YandexSpeechRecognizer(folder_id=FOLDER_ID, iam_token=API_KEY)
    synthesizer = YandexStreamingSynthesizer(folder_id=FOLDER_ID, iam_token=API_KEY)
    llm         = OpenAIClient()

    loop = asyncio.get_running_loop()

    current_lang = "uz-UZ"
    current_voice = "yulduz"

    stt_session      = None
    partial_stt_task = None

    live_mode     = False
    allow_interrupt = False

    is_responding     = False
    response_cancelled = asyncio.Event()
    active_tts_session  = None
    active_response_task = None
    response_generation  = 0
    current_person       = None
    pending_registration = None

    def start_stt():
        nonlocal stt_session, partial_stt_task
        if stt_session:
            try:
                stt_session._chunks.put(None)
            except Exception:
                pass
            stt_session = None
        if partial_stt_task:
            partial_stt_task.cancel()
            partial_stt_task = None

        stt_partial_queue = asyncio.Queue()
        stt_session = SttStreamingSession(recognizer, 16000, loop, stt_partial_queue, current_lang)
        stt_session.start()

        async def send_partial_stt():
            try:
                while True:
                    text = await stt_partial_queue.get()
                    if text is None:
                        break
                    await websocket.send_json({"type": "stt_partial", "text": text})
            except (asyncio.CancelledError, Exception):
                pass

        partial_stt_task = asyncio.create_task(send_partial_stt())

    def stop_stt():
        nonlocal stt_session, partial_stt_task
        if stt_session:
            try:
                stt_session._chunks.put(None)
            except Exception:
                pass
            stt_session = None
        if partial_stt_task:
            partial_stt_task.cancel()
            partial_stt_task = None

    def stop_partial_sender():
        nonlocal partial_stt_task
        if partial_stt_task:
            partial_stt_task.cancel()
            partial_stt_task = None

    def force_cancel_response():
        nonlocal is_responding, active_tts_session, active_response_task, response_generation
        response_generation += 1
        response_cancelled.set()
        if active_tts_session is not None:
            active_tts_session.cancel()
            active_tts_session = None
        if active_response_task and not active_response_task.done():
            active_response_task.cancel()
            active_response_task = None
        is_responding = False

    messages = [{"role": "system",
                 "content": build_system_prompt(current_person, onboarding=False, current_lang=current_lang)}]

    async def process_response(user_text: str, generation: int):
        nonlocal is_responding, active_tts_session, active_response_task
        is_responding = True
        response_cancelled.clear()
        messages[0] = {
            "role": "system",
            "content": build_system_prompt(current_person, onboarding=bool(pending_registration),
                                           current_lang=current_lang),
        }

        tts_audio_queue = asyncio.Queue()
        tts_session     = TtsStreamingSession(synthesizer, 1.1, 48000, loop, tts_audio_queue, current_voice)
        active_tts_session = tts_session
        tts_session.start()

        await websocket.send_json({"type": "response_started", "response_id": generation})

        async def send_tts_audio():
            try:
                while not response_cancelled.is_set() and generation == response_generation:
                    try:
                        audio_chunk = await asyncio.wait_for(tts_audio_queue.get(), timeout=0.02)
                    except asyncio.TimeoutError:
                        continue
                    if audio_chunk is None:
                        break
                    if response_cancelled.is_set() or generation != response_generation:
                        break
                    await websocket.send_json({
                        "type": "tts_chunk",
                        "response_id": generation,
                        "encoding": "linear16",
                        "sample_rate": 48000,
                        "audio": base64.b64encode(audio_chunk).decode("ascii"),
                    })
                while not tts_audio_queue.empty():
                    try:
                        tts_audio_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                if generation == response_generation and not response_cancelled.is_set():
                    await websocket.send_json({"type": "tts_end", "response_id": generation})
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("TTS audio send error: %s", e)

        tts_task        = asyncio.create_task(send_tts_audio())
        full_llm_resp   = ""
        sentence_buf    = ""

        try:
            async for llm_chunk in llm.get_response_stream(messages):
                if response_cancelled.is_set() or generation != response_generation:
                    break
                full_llm_resp += llm_chunk
                await websocket.send_json({"type": "llm_partial", "text": llm_chunk,
                                           "response_id": generation})
                sentence_buf += llm_chunk
                sentence, sentence_buf = flush_sentence_buffer(sentence_buf)
                if sentence:
                    tts_session.feed(sentence)

            if sentence_buf.strip() and not response_cancelled.is_set() and generation == response_generation:
                tts_session.feed(sentence_buf.strip())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("LLM streaming error: %s", e)
            error_text = local_medical_fallback(user_text, current_person)
            if full_llm_resp:
                error_text = "\n\n" + error_text
            full_llm_resp += error_text
            await websocket.send_json({
                "type": "llm_partial",
                "text": error_text,
                "response_id": generation,
            })
            if not response_cancelled.is_set() and generation == response_generation:
                tts_session.feed(error_text.strip())

        try:
            await tts_session.finish()
        except (asyncio.CancelledError, Exception):
            pass

        was_cancelled = response_cancelled.is_set() or generation != response_generation
        if full_llm_resp and not was_cancelled:
            messages.append({"role": "assistant", "content": full_llm_resp})
            await websocket.send_json({
                "type": "llm_done",
                "text": full_llm_resp,
                "response_id": generation,
            })

        try:
            await tts_task
        except asyncio.CancelledError:
            pass

        if active_tts_session is tts_session:
            active_tts_session = None
        if active_response_task is asyncio.current_task():
            active_response_task = None
        if generation == response_generation:
            is_responding = False

        if live_mode and not was_cancelled:
            await websocket.send_json({"type": "ready_to_listen"})

    try:
        while True:
            data = await websocket.receive()

            if "bytes" in data:
                if is_responding and allow_interrupt:
                    force_cancel_response()
                    await websocket.send_json({"type": "interrupt"})
                    start_stt()
                    await websocket.send_json({"type": "stt_ready"})
                if stt_session:
                    stt_session.feed(data["bytes"])

            elif "text" in data:
                msg      = json.loads(data["text"])
                msg_type = msg.get("type")

                if msg_type == "set_language":
                    current_lang = msg.get("lang", "uz-UZ")
                    current_voice = {"uz-UZ": "yulduz", "en-US": "john"}.get(current_lang, "yulduz_ru")

                elif msg_type == "set_settings":
                    live_mode      = msg.get("live_mode", False)
                    allow_interrupt = msg.get("allow_interrupt", False)

                elif msg_type == "start_speech":
                    if is_responding and allow_interrupt:
                        force_cancel_response()
                        await websocket.send_json({"type": "interrupt"})
                    start_stt()
                    await websocket.send_json({"type": "stt_ready"})

                elif msg_type == "interrupt":
                    if is_responding:
                        force_cancel_response()
                        await websocket.send_json({"type": "interrupt"})

                elif msg_type == "face_identity":
                    current_person       = msg.get("person")
                    pending_registration = msg.get("pending_registration")

                    if not is_responding:
                        if current_person:
                            greeting = (
                                f"Oldingizda {current_person.get('first_name','').strip()} turibdi. "
                                "Tanish odamdek iliq salomlashing va yordam taklif qiling."
                            )
                        elif pending_registration:
                            greeting = (
                                "Oldingizda yangi odam turibdi. Salomlashing va so'rang: "
                                '"Keling, tanishib olaylik. Ismingiz va familiyangiz nima?"'
                            )
                        else:
                            greeting = None

                        if greeting:
                            messages.append({"role": "user", "content": greeting})
                            response_generation += 1
                            active_response_task = asyncio.create_task(
                                process_response(greeting, response_generation)
                            )

                elif msg_type == "text_message":
                    final_text = (msg.get("text") or "").strip()
                    if not final_text:
                        continue
                    if is_responding:
                        force_cancel_response()
                    messages.append({"role": "user", "content": final_text})
                    response_generation += 1
                    active_response_task = asyncio.create_task(
                        process_response(final_text, response_generation)
                    )

                elif msg_type == "end_speech":
                    if not stt_session:
                        continue
                    final_text  = await stt_session.finish()
                    stt_session = None
                    stop_partial_sender()

                    if not final_text:
                        stt_error = getattr(recognizer, "last_error", None)
                        if stt_error:
                            await websocket.send_json({
                                "type": "chat_error",
                                "message": (
                                    "Yandex SpeechKit STT ishlamadi. Settings bo'limida "
                                    "Yandex API key va catalog/folder ID bir xil Yandex Cloud "
                                    f"folderdan ekanini tekshiring. Xato: {str(stt_error)[:220]}"
                                ),
                            })
                        await websocket.send_json({"type": "stt_empty"})
                        if live_mode:
                            await websocket.send_json({"type": "ready_to_listen"})
                        continue

                    if pending_registration:
                        extracted = await llm.extract_person_name(final_text)
                        if extracted and extracted.get("is_confident"):
                            current_person = get_face_store().register(
                                embedding=pending_registration["embedding"],
                                first_name=extracted.get("first_name", ""),
                                last_name=extracted.get("last_name", ""),
                                snapshot_path=pending_registration.get("snapshot_path"),
                                metadata={},
                            )
                            pending_registration = None
                            await websocket.send_json({"type": "stt_final", "text": final_text})
                            messages.append({"role": "user", "content": final_text})
                            reg_prompt = (
                                f"Endi siz bu odamni taniysiz: {current_person['full_name']}. "
                                "Ismi bilan qisqa salomlashing."
                            )
                            messages.append({"role": "user", "content": reg_prompt})
                            response_generation += 1
                            active_response_task = asyncio.create_task(
                                process_response(reg_prompt, response_generation)
                            )
                            continue

                    if is_responding:
                        force_cancel_response()

                    await websocket.send_json({"type": "stt_final", "text": final_text})
                    messages.append({"role": "user", "content": final_text})
                    response_generation += 1
                    active_response_task = asyncio.create_task(
                        process_response(final_text, response_generation)
                    )

    except WebSocketDisconnect:
        logger.info("WS /ws/chat disconnected")
    except RuntimeError as e:
        if "Cannot call" not in str(e):
            logger.error("RuntimeError in WS: %s", e)
    except Exception as e:
        logger.error("WS error: %s", e)
    finally:
        stop_stt()
        if is_responding or active_response_task:
            force_cancel_response()


# ═══════════════════════════════════════════════════════════════════
#  THERMAL CAMERA
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/thermal")
async def thermal_snapshot():
    """Single frame from MLX90640. Always returns JSON even when disabled."""
    data = await asyncio.to_thread(_read_thermal_source)
    return JSONResponse(data)


@app.get("/api/thermal/state")
async def thermal_state():
    return JSONResponse({
        "ok": True,
        "enabled": bool(_thermal_runtime.get("enabled")),
        "hardware_ready": bool(_thermal.enabled),
        "reason": None if _thermal.enabled else _thermal.reason,
        "message": _thermal.message,
        "install": None if _thermal.enabled else THERMAL_INSTALL_COMMAND,
    })


@app.post("/api/thermal/state")
async def thermal_set_state(payload: dict):
    enabled = bool(payload.get("enabled"))
    state = await asyncio.to_thread(_set_thermal_enabled, enabled)
    return JSONResponse(state)


@app.post("/api/thermal/push")
async def thermal_push(payload: dict):
    """Accept one 32x24 MLX90640 frame from a Raspberry Pi thermal agent."""
    try:
        source = str(payload.get("source") or "raspberry_pi")
        data = _normalize_thermal_payload(payload, source=source)
    except Exception as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

    _remote_thermal["data"] = data
    _remote_thermal["updated_at"] = time.time()
    _remote_thermal["source"] = source
    return JSONResponse({"ok": True, "source": source, "max": data["max"]})


@app.websocket("/ws/thermal")
async def thermal_ws(websocket: WebSocket):
    """
    Streams one 32×24 frame every 250 ms (≈4 Hz).
    Payload JSON: {ok, frame:[768 floats], max, min, avg, center, rows, cols}
    When sensor is not connected → {ok:false, reason:'not_connected'}
    """
    await websocket.accept()
    logger.info("WS /ws/thermal connected")
    try:
        while True:
            data = await asyncio.to_thread(_read_thermal_source)
            await websocket.send_json(data)
            await asyncio.sleep(0.25)   # 4 Hz
    except WebSocketDisconnect:
        logger.info("WS /ws/thermal disconnected")
    except Exception as e:
        logger.error("Thermal WS error: %s", e)


# ═══════════════════════════════════════════════════════════════════
#  FRONTEND
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
async def get():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("UZMAX_HOST", "0.0.0.0")
    port = int(os.getenv("UZMAX_PORT", "5000"))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_check:
        try:
            port_check.bind((host, port))
        except OSError:
            print(f"ERROR: Port {port} is already in use.")
            print("Stop the existing UzMAX server or set UZMAX_PORT to another port.")
            raise SystemExit(1)

    print("=" * 56)
    print(f"  UzMAX Unified Server  ->  http://127.0.0.1:{port}")
    print(f"  LAN/server link       ->  http://YOUR_SERVER_IP:{port}")
    print("  Medical AI  +  Robot Control (HAND/HEAD/MOVE)")
    print("=" * 56)
    uvicorn.run(app, host=host, port=port, log_level="info")
