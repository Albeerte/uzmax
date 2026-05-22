"""
UzMAX Robot — FastAPI Server
============================
Deployed on a public server. Handles:
  • /ws/robot/{robot_id}   ← WebSocket from Raspberry Pi agent
  • /ws/dashboard          ← WebSocket for dashboard browsers
  • /api/robot/…           ← REST control endpoints
  • /api/voice/ask         ← STT → RAG → TTS pipeline
  • /dashboard             ← Serves dashboard HTML

Setup:
    pip install fastapi uvicorn python-multipart websockets

Run:
    uvicorn main:app --host 0.0.0.0 --port 8000

Environment variables:
    YANDEX_API_KEY      — Yandex SpeechKit IAM token
    YANDEX_FOLDER_ID    — Yandex catalog ID
"""

import os
import uuid
import asyncio
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uzmax")

# ── App ───────────────────────────────────────────────────────────
app = FastAPI(title="UzMAX Robot Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (audio answers, etc.)
os.makedirs("static", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Config ────────────────────────────────────────────────────────
YANDEX_API_KEY   = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")

# ── State ─────────────────────────────────────────────────────────
# Last known status payload from each robot
robots: Dict[str, Any] = {}

# Active robot WebSocket connections
robot_sockets: Dict[str, WebSocket] = {}

# Active dashboard WebSocket connections
dashboard_sockets: list[WebSocket] = []


# =================================================================
#  HEALTH CHECK
# =================================================================

@app.get("/")
def home():
    return {"status": "UzMAX server working", "robots": list(robots.keys())}


# =================================================================
#  ROBOT WEBSOCKET  (Raspberry Pi → Server)
# =================================================================

@app.websocket("/ws/robot/{robot_id}")
async def robot_ws(websocket: WebSocket, robot_id: str):
    await websocket.accept()
    robot_sockets[robot_id] = websocket
    logger.info("Robot connected: %s", robot_id)

    try:
        while True:
            data = await websocket.receive_json()
            robots[robot_id] = data

            # Forward camera frame + status to all dashboard clients
            dashboard_payload = {k: v for k, v in data.items() if k != "camera_image"}
            camera_payload = {
                "type":         "robot_frame",
                "robot_id":     robot_id,
                "camera_image": data.get("camera_image"),
                "person":       data.get("person"),
                "temperature":  data.get("temperature"),
                "faces":        data.get("faces"),
            }

            dead = []
            for ws in dashboard_sockets:
                try:
                    await ws.send_json(camera_payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                dashboard_sockets.remove(ws)

    except WebSocketDisconnect:
        logger.info("Robot disconnected: %s", robot_id)
    except Exception as e:
        logger.error("Robot WS error %s: %s", robot_id, e)
    finally:
        robot_sockets.pop(robot_id, None)
        robots.pop(robot_id, None)


# =================================================================
#  DASHBOARD WEBSOCKET  (Browser → Server, read-only stream)
# =================================================================

@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await websocket.accept()
    dashboard_sockets.append(websocket)
    logger.info("Dashboard connected")

    try:
        # Send current state immediately
        await websocket.send_json({
            "type":   "robots",
            "robots": {rid: {k: v for k, v in data.items() if k != "camera_image"}
                       for rid, data in robots.items()},
        })

        while True:
            # Keep connection alive; camera frames are pushed by robot_ws
            await asyncio.sleep(5)
            await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in dashboard_sockets:
            dashboard_sockets.remove(websocket)


# =================================================================
#  ROBOT CONTROL REST ENDPOINTS
# =================================================================

async def _send_to_robot(robot_id: str, payload: dict) -> JSONResponse:
    """Helper: send JSON command to robot via its WebSocket."""
    ws = robot_sockets.get(robot_id)
    if not ws:
        return JSONResponse({"ok": False, "error": f"Robot '{robot_id}' not connected"}, status_code=404)

    try:
        await ws.send_json(payload)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/robots")
def list_robots():
    return {"robots": [
        {"robot_id": rid, "person": data.get("person"), "temperature": data.get("temperature")}
        for rid, data in robots.items()
    ]}


@app.post("/api/robot/{robot_id}/move")
async def move_robot(
    robot_id: str,
    action: str = Form(...),   # FWD | BACK | LEFT | RIGHT | STOP
    speed:  int = Form(150),
):
    return await _send_to_robot(robot_id, {"type": "move", "action": action, "speed": speed})


@app.post("/api/robot/{robot_id}/gesture")
async def gesture_robot(robot_id: str, name: str = Form(...)):
    return await _send_to_robot(robot_id, {"type": "gesture", "name": name})


@app.post("/api/robot/{robot_id}/serial")
async def send_serial(
    robot_id: str,
    device:  str = Form(...),   # HAND | HEAD | MOVE
    command: str = Form(...),
):
    return await _send_to_robot(robot_id, {"type": "serial", "device": device, "command": command})


@app.post("/api/robot/{robot_id}/record")
async def start_record(robot_id: str):
    return await _send_to_robot(robot_id, {"type": "record_voice"})


@app.post("/api/robot/{robot_id}/led")
async def set_led(
    robot_id: str,
    r: int = Form(0),
    g: int = Form(0),
    b: int = Form(0),
):
    return await _send_to_robot(robot_id, {"type": "led", "r": r, "g": g, "b": b})


# =================================================================
#  VOICE  (STT → RAG → TTS)
# =================================================================

def _yandex_stt(audio_path: str, language: str = "uz-UZ") -> str:
    """
    Send WAV to Yandex SpeechKit STT.
    Returns recognised text.
    Replace this stub with real Yandex API call when ready.
    """
    if not YANDEX_API_KEY:
        logger.warning("YANDEX_API_KEY not set — using placeholder STT")
        return "Assalomu alaykum, haroratim nechchi?"

    import requests as req
    url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
    params = {"folderId": YANDEX_FOLDER_ID, "lang": language}

    with open(audio_path, "rb") as f:
        r = req.post(url, params=params, data=f,
                     headers={"Authorization": f"Api-Key {YANDEX_API_KEY}",
                               "Content-Type": "audio/x-wav"},
                     timeout=30)
    r.raise_for_status()
    return r.json().get("result", "")


def _rag_answer(question: str, person_name: str, temperature: Optional[str]) -> str:
    """
    Simple rule-based RAG.  Replace with vector DB + LLM when ready.
    """
    q    = question.lower()
    name = person_name if person_name and person_name != "Unknown" else ""
    greet = f"{name}, " if name else ""

    if any(w in q for w in ["harorat", "temperatura", "isitma", "temperature"]):
        temp_str = f"{temperature} daraja" if temperature else "aniqlanmadi"
        return (f"{greet}sizning yuz haroratingiz taxminan {temp_str}. "
                "Bu dastlabki skrining natijasi. Shifokor bilan maslahatlashing.")

    if any(w in q for w in ["doktor", "shifokor", "qabul"]):
        return f"{greet}qaysi shifokorga yozilmoqchisiz? Terapevt, kardiolog yoki boshqa mutaxassis?"

    if any(w in q for w in ["salom", "assalomu", "привет", "hello"]):
        return f"Assalomu alaykum{', ' + name if name else ''}! Men UzMAX robotman. Sizga qanday yordam bera olaman?"

    if any(w in q for w in ["rahmat", "raxmat"]):
        return "Arzimaydi! Yana murojaat qilishingiz mumkin."

    return f"{greet}sizni eshitdim. Aniqroq so'rasangiz yordam bera olaman."


def _yandex_tts(text: str, voice: str = "yulduz", language: str = "uz-UZ") -> str:
    """
    Synthesize text via Yandex SpeechKit TTS.
    Returns path to saved WAV file.
    """
    filename = f"static/tts_{uuid.uuid4()}.wav"

    if not YANDEX_API_KEY:
        logger.warning("YANDEX_API_KEY not set — writing text placeholder instead of audio")
        txt_path = filename.replace(".wav", ".txt")
        Path(txt_path).write_text(text, encoding="utf-8")
        return "/" + txt_path

    import requests as req
    url = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
    data = {
        "folderId": YANDEX_FOLDER_ID,
        "text":     text,
        "lang":     language,
        "voice":    voice,
        "format":   "lpcm",
        "sampleRateHertz": "16000",
    }
    r = req.post(url, data=data,
                 headers={"Authorization": f"Api-Key {YANDEX_API_KEY}"},
                 timeout=30)
    r.raise_for_status()

    Path(filename).write_bytes(r.content)
    return "/" + filename


@app.post("/api/voice/ask")
async def voice_ask(
    robot_id:    str = Form(...),
    person_name: str = Form("Unknown"),
    temperature: str = Form(""),
    language:    str = Form("uz-UZ"),
    audio: UploadFile = File(...),
):
    # Save uploaded audio
    audio_path = f"uploads/{uuid.uuid4()}.wav"
    Path(audio_path).write_bytes(await audio.read())

    # Run heavy work in thread pool
    loop = asyncio.get_event_loop()

    recognized_text = await loop.run_in_executor(None, _yandex_stt, audio_path, language)
    logger.info("STT [%s]: %s", robot_id, recognized_text)

    answer_text = _rag_answer(recognized_text, person_name, temperature or None)
    logger.info("RAG [%s]: %s", robot_id, answer_text)

    audio_url = await loop.run_in_executor(None, _yandex_tts, answer_text, "yulduz", language)

    return {
        "recognized_text": recognized_text,
        "answer":          answer_text,
        "audio_url":       audio_url,
        "person_name":     person_name,
        "temperature":     temperature,
    }


# =================================================================
#  DASHBOARD HTML
# =================================================================

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    html_path = Path("dashboard.html")
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>dashboard.html not found</h1>")


# =================================================================
#  ENTRY POINT
# =================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
