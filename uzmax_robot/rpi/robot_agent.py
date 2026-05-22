"""
UzMAX Robot — Raspberry Pi Agent
=================================
Runs on RPi 5. Connects to:
  • 3x ESP32 via USB serial (auto-detect by DEVICE: handshake)
  • Camera (face detection + recognition)
  • MLX90640 (thermal temperature)
  • Server via WebSocket (receives commands, streams camera + data)

Usage:
    python3 robot_agent.py

Requirements (RPi):
    sudo apt install -y python3-opencv python3-numpy i2c-tools portaudio19-dev
    pip3 install pyserial websockets sounddevice scipy requests \
                 adafruit-circuitpython-mlx90640 face_recognition --break-system-packages
"""

import os
import cv2
import time
import json
import base64
import asyncio
import threading
import serial
import serial.tools.list_ports
import numpy as np
import requests
import websockets
import sounddevice as sd
from scipy.io.wavfile import write as wav_write

# ── Thermal (optional — gracefully disabled if not connected) ────
try:
    import board
    import busio
    import adafruit_mlx90640
    THERMAL_AVAILABLE = True
except ImportError:
    THERMAL_AVAILABLE = False

# ── Face recognition ─────────────────────────────────────────────
try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    print("[WARN] face_recognition not installed — using OpenCV Haar fallback")

# =================================================================
#  CONFIGURATION  (edit these)
# =================================================================

ROBOT_ID          = "uzmax-001"

SERVER_WS         = "wss://YOUR_DOMAIN/ws/robot/uzmax-001"
SERVER_API        = "https://YOUR_DOMAIN/api"

KNOWN_FACES_DIR   = "known_faces"

SERIAL_BAUD       = 115200

VOICE_RECORD_SECS = 5
VOICE_SAMPLERATE  = 16000
VOICE_FILE        = "/tmp/uzmax_voice.wav"

CAMERA_INDEX      = 0
CAMERA_STREAM_W   = 640
CAMERA_STREAM_H   = 360
CAMERA_JPEG_Q     = 70

FACE_SCAN_INTERVAL = 0.5   # seconds between face recognition runs (expensive)

# =================================================================
#  ESP32 SERIAL MANAGER
# =================================================================

class ESP32Manager:
    """Auto-detect and communicate with HAND / HEAD / MOVE ESP32s."""

    def __init__(self):
        self.devices: dict[str, serial.Serial | None] = {
            "HAND": None,
            "HEAD": None,
            "MOVE": None,
        }
        self._locks: dict[str, threading.Lock] = {
            k: threading.Lock() for k in self.devices
        }

    def scan(self):
        """Scan all COM ports and identify each ESP32 by DEVICE: handshake."""
        ports = serial.tools.list_ports.comports()
        print(f"[SCAN] Found {len(ports)} serial port(s)")

        for port_info in ports:
            device_path = port_info.device
            print(f"[SCAN] Trying {device_path} …")

            try:
                ser = serial.Serial(device_path, SERIAL_BAUD, timeout=1)
                time.sleep(2)           # wait for ESP32 boot/reset

                # Send PING and read response
                ser.write(b"PING\n")
                time.sleep(0.3)

                lines = []
                while ser.in_waiting:
                    line = ser.readline().decode(errors="ignore").strip()
                    if line:
                        lines.append(line)
                text = "\n".join(lines)

                # Identify device
                identified = False
                for name in ["HAND", "HEAD", "MOVE"]:
                    if f"DEVICE:{name}" in text:
                        with self._locks[name]:
                            if self.devices[name] and self.devices[name].is_open:
                                self.devices[name].close()
                            self.devices[name] = ser
                        print(f"[SCAN] {name} ← {device_path}")
                        identified = True
                        break

                if not identified:
                    ser.close()
                    print(f"[SCAN] {device_path} unknown device, closed")

            except Exception as e:
                print(f"[SCAN] {device_path} error: {e}")

        connected = [k for k, v in self.devices.items() if v and v.is_open]
        print(f"[SCAN] Done. Connected: {connected or 'none'}")

    def send(self, device: str, command: str) -> tuple[bool, str]:
        """Thread-safe send to device. Returns (success, response)."""
        lock = self._locks.get(device)
        if lock is None:
            return False, "Unknown device"

        with lock:
            ser = self.devices.get(device)
            if ser is None or not ser.is_open:
                print(f"[SERIAL] {device} not connected")
                return False, "Not connected"

            try:
                ser.write((command + "\n").encode())
                time.sleep(0.05)

                response = ""
                while ser.in_waiting:
                    response += ser.readline().decode(errors="ignore").strip() + "\n"

                resp = response.strip()
                print(f"[{device}] → {command}  ← {resp}")
                return True, resp
            except Exception as e:
                print(f"[SERIAL] {device} error: {e}")
                return False, str(e)

    # ── Convenience wrappers ─────────────────────────────────────

    def hand(self, side: str, servo: int, angle: int):
        return self.send("HAND", f"HAND {side} {servo} {angle}")

    def hand_all(self, angle: int):
        return self.send("HAND", f"HAND ALL {angle}")

    def head_servo(self, servo: int, angle: int):
        return self.send("HEAD", f"HEAD SERVO {servo} {angle}")

    def head_led(self, r: int, g: int, b: int):
        return self.send("HEAD", f"HEAD LED {r} {g} {b}")

    def head_led_off(self):
        return self.send("HEAD", "HEAD LED_OFF")

    def head_rainbow(self):
        return self.send("HEAD", "HEAD RAINBOW")

    def move(self, action: str, speed: int = 150):
        if action.upper() == "STOP":
            return self.send("MOVE", "MOVE STOP")
        return self.send("MOVE", f"MOVE {action.upper()} {speed}")


# =================================================================
#  FACE RECOGNITION SYSTEM
# =================================================================

class FaceSystem:
    def __init__(self):
        self.known_encodings: list = []
        self.known_names: list[str] = []
        self._cascade = None

        if not FACE_RECOGNITION_AVAILABLE:
            # Fallback: OpenCV Haar cascade (no identification)
            self._cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
        else:
            self._load_known_faces()

    def _load_known_faces(self):
        os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
        print("[FACE] Loading known faces …")

        for fn in os.listdir(KNOWN_FACES_DIR):
            if not fn.lower().endswith((".jpg", ".jpeg", ".png")):
                continue

            path = os.path.join(KNOWN_FACES_DIR, fn)
            name = os.path.splitext(fn)[0]

            img = face_recognition.load_image_file(path)
            encs = face_recognition.face_encodings(img)

            if encs:
                self.known_encodings.append(encs[0])
                self.known_names.append(name)
                print(f"[FACE] Loaded: {name}")
            else:
                print(f"[FACE] No face in: {fn}")

        print(f"[FACE] {len(self.known_names)} face(s) loaded")

    def recognize(self, frame: np.ndarray) -> list[dict]:
        """Return list of {name, box:[l,t,r,b]} for each detected face."""

        if not FACE_RECOGNITION_AVAILABLE:
            # Haar fallback — detect only, no identification
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            rects = self._cascade.detectMultiScale(gray, 1.1, 4)
            results = []
            for (x, y, w, h) in rects:
                results.append({"name": "Unknown", "box": [x, y, x+w, y+h]})
            return results

        # Downsample for speed
        small = cv2.resize(
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            (0, 0), fx=0.5, fy=0.5
        )

        locations = face_recognition.face_locations(small, model="hog")
        encodings = face_recognition.face_encodings(small, locations)

        results = []
        for enc, loc in zip(encodings, locations):
            name = "Unknown"

            if self.known_encodings:
                distances = face_recognition.face_distance(self.known_encodings, enc)
                best_idx  = int(np.argmin(distances))
                if float(distances[best_idx]) < 0.50:
                    name = self.known_names[best_idx]

            top, right, bottom, left = loc
            results.append({
                "name": name,
                "box": [left*2, top*2, right*2, bottom*2],  # rescale back
            })

        return results


# =================================================================
#  THERMAL MLX90640
# =================================================================

class ThermalSystem:
    def __init__(self):
        self.enabled = False
        self._frame  = [0.0] * 768
        self._mlx    = None

        if not THERMAL_AVAILABLE:
            print("[THERMAL] adafruit libraries not installed — disabled")
            return

        try:
            i2c = busio.I2C(board.SCL, board.SDA, frequency=400_000)
            self._mlx = adafruit_mlx90640.MLX90640(i2c)
            self._mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_4_HZ
            self.enabled = True
            print("[THERMAL] MLX90640 ready")
        except Exception as e:
            print(f"[THERMAL] MLX90640 not found: {e}")

    def read(self) -> dict:
        if not self.enabled or self._mlx is None:
            return {"ok": False, "center": None, "max": None, "min": None, "avg": None}

        try:
            self._mlx.getFrame(self._frame)
            t = np.array(self._frame).reshape((24, 32))
            return {
                "ok":     True,
                "center": round(float(t[12, 16]), 1),
                "max":    round(float(np.max(t)), 1),
                "min":    round(float(np.min(t)), 1),
                "avg":    round(float(np.mean(t)), 1),
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "center": None, "max": None, "min": None, "avg": None}


# =================================================================
#  VOICE HELPERS
# =================================================================

def record_voice(seconds: int = VOICE_RECORD_SECS) -> str:
    print(f"[VOICE] Recording {seconds}s …")
    audio = sd.rec(int(seconds * VOICE_SAMPLERATE),
                   samplerate=VOICE_SAMPLERATE, channels=1, dtype="int16")
    sd.wait()
    wav_write(VOICE_FILE, VOICE_SAMPLERATE, audio)
    print(f"[VOICE] Saved to {VOICE_FILE}")
    return VOICE_FILE


def ask_server_voice(wav_path: str, person_name: str, temp: float | None) -> dict:
    with open(wav_path, "rb") as f:
        files = {"audio": ("voice.wav", f, "audio/wav")}
        data  = {
            "robot_id":    ROBOT_ID,
            "person_name": person_name or "Unknown",
            "temperature": str(temp) if temp is not None else "",
            "language":    "uz-UZ",
        }
        r = requests.post(f"{SERVER_API}/voice/ask", files=files, data=data, timeout=90)
    r.raise_for_status()
    return r.json()


def play_audio_url(url: str):
    if not url.startswith("http"):
        url = SERVER_API.replace("/api", "") + url

    audio_path = "/tmp/uzmax_answer.wav"
    r = requests.get(url, timeout=60)
    r.raise_for_status()

    with open(audio_path, "wb") as f:
        f.write(r.content)

    os.system(f"aplay {audio_path}")


# =================================================================
#  GESTURE PRESETS
# =================================================================

def do_gesture(esp: ESP32Manager, name: str):
    """Execute named gesture via ESP32_HAND."""
    if name == "hello":
        esp.head_servo(1, 60)
        time.sleep(0.3)
        esp.head_servo(1, 90)
        esp.hand("R", 1, 60)
        esp.hand("R", 2, 120)
        esp.hand("R", 3, 150)
        esp.hand("R", 4, 80)

    elif name == "open_hand":
        esp.hand_all(90)

    elif name == "fist":
        for s in range(1, 7):
            esp.hand("R", s, 0)
            esp.hand("L", s, 0)

    elif name == "wave":
        for _ in range(3):
            esp.hand("R", 1, 30)
            time.sleep(0.3)
            esp.hand("R", 1, 90)
            time.sleep(0.3)

    elif name == "nod":
        esp.head_servo(2, 70)
        time.sleep(0.4)
        esp.head_servo(2, 90)

    else:
        print(f"[GESTURE] Unknown gesture: {name}")


# =================================================================
#  MAIN ROBOT COROUTINE
# =================================================================

async def robot_main():
    esp     = ESP32Manager()
    esp.scan()

    face_sys    = FaceSystem()
    thermal_sys = ThermalSystem()

    cam = cv2.VideoCapture(CAMERA_INDEX)
    if not cam.isOpened():
        print("[CAM] WARNING: camera not opened")

    current_person = "Unknown"
    current_temp   = None

    last_face_scan = 0.0
    cached_faces: list[dict] = []

    print("[ROBOT] Starting main loop …")

    while True:
        try:
            async with websockets.connect(SERVER_WS, ping_interval=20) as ws:
                print("[WS] Connected to server")
                esp.head_led(0, 0, 255)   # blue = connected

                while True:
                    # ── Capture camera frame ──────────────────────
                    ok, frame = cam.read()
                    if not ok:
                        await asyncio.sleep(0.3)
                        continue

                    # ── Face recognition (throttled) ──────────────
                    now = time.monotonic()
                    if now - last_face_scan >= FACE_SCAN_INTERVAL:
                        last_face_scan = now
                        # Run in thread pool so it doesn't block async loop
                        loop = asyncio.get_event_loop()
                        cached_faces = await loop.run_in_executor(
                            None, face_sys.recognize, frame.copy()
                        )

                    # Draw boxes on frame
                    current_person = "Unknown"
                    for f in cached_faces:
                        name = f["name"]
                        l, t, r, b = f["box"]
                        current_person = name
                        color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)
                        cv2.rectangle(frame, (l, t), (r, b), color, 2)
                        cv2.putText(frame, name, (l, t - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

                    # ── Thermal read ──────────────────────────────
                    thermal = thermal_sys.read()
                    if thermal.get("ok"):
                        current_temp = thermal.get("max")

                    # ── Encode frame as JPEG base64 ───────────────
                    small = cv2.resize(frame, (CAMERA_STREAM_W, CAMERA_STREAM_H))
                    _, buf = cv2.imencode(".jpg", small,
                                          [int(cv2.IMWRITE_JPEG_QUALITY), CAMERA_JPEG_Q])
                    img_b64 = base64.b64encode(buf).decode()

                    # ── Send status payload to server ─────────────
                    payload = {
                        "type":         "robot_status",
                        "robot_id":     ROBOT_ID,
                        "person":       current_person,
                        "faces":        cached_faces,
                        "temperature":  thermal,
                        "camera_image": img_b64,
                        "timestamp":    time.time(),
                    }
                    await ws.send(json.dumps(payload))

                    # ── Receive commands (non-blocking 50 ms) ─────
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=0.05)
                        cmd = json.loads(msg)
                        cmd_type = cmd.get("type", "")

                        if cmd_type == "serial":
                            device  = cmd.get("device", "")
                            command = cmd.get("command", "")
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, esp.send, device, command)

                        elif cmd_type == "move":
                            action = cmd.get("action", "STOP")
                            speed  = int(cmd.get("speed", 150))
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, esp.move, action, speed)

                        elif cmd_type == "gesture":
                            gesture_name = cmd.get("name", "")
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, do_gesture, esp, gesture_name)

                        elif cmd_type == "record_voice":
                            esp.head_led(255, 120, 0)   # orange = recording
                            loop = asyncio.get_event_loop()
                            wav = await loop.run_in_executor(None, record_voice)
                            answer = await loop.run_in_executor(
                                None, ask_server_voice, wav, current_person, current_temp
                            )
                            esp.head_led(0, 255, 0)     # green = speaking
                            if answer.get("audio_url"):
                                await loop.run_in_executor(
                                    None, play_audio_url, answer["audio_url"]
                                )
                            esp.head_led(0, 0, 255)     # back to blue

                        elif cmd_type == "led":
                            r = int(cmd.get("r", 0))
                            g = int(cmd.get("g", 0))
                            b = int(cmd.get("b", 0))
                            esp.head_led(r, g, b)

                    except asyncio.TimeoutError:
                        pass   # no message this cycle

                    await asyncio.sleep(0.3)

        except Exception as e:
            print(f"[WS] Connection error: {e}")
            esp.head_led(255, 0, 0)   # red = disconnected
            await asyncio.sleep(3)


# =================================================================
#  ENTRY POINT
# =================================================================

if __name__ == "__main__":
    print("=" * 54)
    print("  UzMAX Robot Agent")
    print(f"  Robot ID  : {ROBOT_ID}")
    print(f"  Server WS : {SERVER_WS}")
    print("=" * 54)
    asyncio.run(robot_main())
