# ===== PYTHON FLASK BACKEND (move.py) =====

from flask import Flask, render_template, request, jsonify
import serial
import threading

app = Flask(__name__)

# ──── SET YOUR PORT HERE ────
SERIAL_PORT = 'COM4'
BAUD_RATE = 115200
# ────────────────────────────

ser = None
ser_lock = threading.Lock()


def connect_serial():
    """Connect to the configured serial port."""
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"[OK] Connected to {SERIAL_PORT}")
        return True
    except Exception as e:
        print(f"[!] Could not open {SERIAL_PORT}: {e}")
        print("    Running in SIMULATION mode (no hardware).")
        ser = None
        return False


connect_serial()


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/api/command', methods=['POST'])
def handle_command():
    global ser
    data = request.json
    cmd = data.get('command', '')
    connected = False

    with ser_lock:
        # If disconnected, try to reconnect
        if ser is None or not ser.is_open:
            connect_serial()

        if ser and ser.is_open:
            try:
                if cmd != 'ping':
                    ser.write((cmd + '\n').encode('utf-8'))
                connected = True
            except serial.SerialException:
                print("[!] Serial connection lost. Will retry next command.")
                ser = None
                connected = False

    return jsonify({"status": "ok", "sent": cmd, "serial_connected": connected})


if __name__ == '__main__':
    print("\n" + "="*50)
    print("  Robot Control Server")
    print("="*50)
    print(f"\n  Serial port: {SERIAL_PORT}")
    print(f"  Open http://localhost:5000 in your browser")
    print("="*50 + "\n")

    app.run(host='0.0.0.0', port=5000)