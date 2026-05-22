# ================================================================
#  AXON Robot – Unified Control Server
#  Two independent ESP32 serial connections:
#    • MOVEMENT ESP32  →  /api/command
#    • HAND ESP32      →  /send
# ================================================================

from flask import Flask, render_template, request, jsonify
import serial
import serial.tools.list_ports
import threading
import time

app = Flask(__name__)

BAUD_RATE = 115200

# ─── Per-device serial state ───────────────────────────────────────
_devices = {
    "move": {"ser": None, "port": None, "lock": threading.Lock()},
    "hand": {"ser": None, "port": None, "lock": threading.Lock()},
    "head": {"ser": None, "port": None, "lock": threading.Lock()},
}


# ─── Helpers ───────────────────────────────────────────────────────

def _connect(device: str, port: str) -> dict:
    """Open *port* for *device*. Returns {ok, message}."""
    dev = _devices[device]
    with dev["lock"]:
        # Close existing connection first
        if dev["ser"] and dev["ser"].is_open:
            try:
                dev["ser"].close()
            except Exception:
                pass
        try:
            dev["ser"]  = serial.Serial(port, BAUD_RATE, timeout=1)
            dev["port"] = port
            time.sleep(2)          # let ESP32 boot/reset
            print(f"[OK] {device.upper()} connected → {port}")
            return {"ok": True,  "message": f"Connected to {port}"}
        except Exception as e:
            dev["ser"]  = None
            dev["port"] = None
            print(f"[!] {device.upper()} failed on {port}: {e}")
            return {"ok": False, "message": str(e)}


def _send(device: str, command: str) -> tuple[bool, str]:
    """
    Thread-safe send to *device*.
    Returns (serial_connected, response_text).
    """
    dev      = _devices[device]
    response = ""

    with dev["lock"]:
        ser = dev["ser"]
        if ser is None or not ser.is_open:
            return False, "No serial connection"
        try:
            if command and command != "ping":
                ser.write((command + "\n").encode("utf-8"))
                time.sleep(0.1)
                while ser.in_waiting:
                    response += ser.readline().decode(errors="ignore").strip() + "\n"
            return True, response.strip() or "Command sent"
        except serial.SerialException as exc:
            print(f"[!] {device.upper()} serial lost: {exc}")
            dev["ser"] = None
            return False, f"Serial error: {exc}"


def _status(device: str) -> dict:
    dev = _devices[device]
    connected = dev["ser"] is not None and dev["ser"].is_open
    return {"connected": connected, "port": dev["port"]}


# ─── Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ---- Scan available COM ports ------------------------------------
@app.route("/ports")
def list_ports():
    ports = [
        {"device": p.device, "description": p.description}
        for p in serial.tools.list_ports.comports()
    ]
    return jsonify(ports)


# ---- Connect a device to a chosen port ---------------------------
@app.route("/connect", methods=["POST"])
def connect_device():
    data   = request.get_json(silent=True) or {}
    device = data.get("device", "")    # "move" or "hand"
    port   = data.get("port",   "")
    if device not in _devices:
        return jsonify({"ok": False, "message": "Unknown device"}), 400
    if not port:
        return jsonify({"ok": False, "message": "No port specified"}), 400
    result = _connect(device, port)
    return jsonify(result)


# ---- Disconnect a device -----------------------------------------
@app.route("/disconnect", methods=["POST"])
def disconnect_device():
    data   = request.get_json(silent=True) or {}
    device = data.get("device", "")
    if device not in _devices:
        return jsonify({"ok": False, "message": "Unknown device"}), 400
    dev = _devices[device]
    with dev["lock"]:
        if dev["ser"] and dev["ser"].is_open:
            dev["ser"].close()
        dev["ser"]  = None
        dev["port"] = None
    return jsonify({"ok": True, "message": "Disconnected"})


# ---- Status of all devices ---------------------------------------
@app.route("/status")
def device_status():
    return jsonify({device: _status(device) for device in _devices})


# ---- Movement endpoint -------------------------------------------
@app.route("/api/command", methods=["POST"])
def api_command():
    data = request.get_json(silent=True) or {}
    cmd  = data.get("command", "")
    connected, response = _send("move", cmd)
    return jsonify({
        "status"          : "ok",
        "sent"            : cmd,
        "response"        : response,
        "serial_connected": connected,
    })


# ---- Hand / servo endpoint ---------------------------------------
@app.route("/send", methods=["POST"])
def send_hand():
    data    = request.get_json(silent=True) or {}
    command = data.get("command", "")
    connected, response = _send("hand", command)
    return jsonify({
        "command"         : command,
        "response"        : response,
        "serial_connected": connected,
    })


# ---- Head (360° servo + LED strip) endpoint ----------------------
@app.route("/head", methods=["POST"])
def send_head():
    data    = request.get_json(silent=True) or {}
    command = data.get("command", "")
    connected, response = _send("head", command)
    return jsonify({
        "command"         : command,
        "response"        : response,
        "serial_connected": connected,
    })


# ─── Entry point ───────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 54)
    print("  AXON – Unified Robot Control Server")
    print("  Movement | Hand | Head ESP32 — independent ports")
    print("=" * 54)
    print(f"\n  Open : http://localhost:5000")
    print("  Select COM ports in the browser UI")
    print("=" * 54 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
