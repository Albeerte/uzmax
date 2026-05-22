from flask import Flask, render_template_string, request, jsonify
import serial
import serial.tools.list_ports
import time

app = Flask(__name__)

SERIAL_PORT = "COM6"       # Windows example
# SERIAL_PORT = "/dev/ttyUSB0"   # Raspberry Pi / Linux example

BAUD_RATE = 115200

ser = None


def connect_serial():
    global ser

    if ser and ser.is_open:
        return ser

    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)

    return ser


def send_command(command):
    try:
        s = connect_serial()
        s.write((command + "\n").encode())
        time.sleep(0.1)

        response = ""

        while s.in_waiting:
            response += s.readline().decode(errors="ignore").strip() + "\n"

        return response.strip() or "Command sent"

    except Exception as e:
        return f"Serial error: {e}"


HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>UZMAX Hand Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #0f172a;
            color: white;
        }

        .container {
            max-width: 1200px;
            margin: auto;
            padding: 25px;
        }

        h1 {
            text-align: center;
            color: #38bdf8;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 18px;
        }

        .card {
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 18px;
            padding: 18px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.3);
        }

        .card h2 {
            margin-top: 0;
            color: #93c5fd;
        }

        .servo-box {
            margin: 14px 0;
        }

        label {
            display: flex;
            justify-content: space-between;
            margin-bottom: 5px;
        }

        input[type=range] {
            width: 100%;
        }

        button {
            border: none;
            border-radius: 12px;
            padding: 13px 18px;
            margin: 5px;
            background: #2563eb;
            color: white;
            font-size: 15px;
            cursor: pointer;
        }

        button:hover {
            background: #1d4ed8;
        }

        .danger {
            background: #dc2626;
        }

        .green {
            background: #16a34a;
        }

        .orange {
            background: #ea580c;
        }

        .status {
            margin-top: 20px;
            background: black;
            padding: 15px;
            border-radius: 12px;
            min-height: 60px;
            color: #22c55e;
            white-space: pre-wrap;
        }
    </style>
</head>

<body>
<div class="container">
    <h1>UZMAX Robot Hand Control</h1>

    <div class="card">
        <h2>Main Actions</h2>
        <button onclick="sendCmd('ALL_START')" class="green">All Start</button>
        <button onclick="sendCmd('RIGHT_START')">Right Start</button>
        <button onclick="sendCmd('LEFT_START')">Left Start</button>
        <button onclick="sendCmd('OPEN')" class="green">Open Hands</button>
        <button onclick="sendCmd('FIST')" class="danger">Fist</button>
        <button onclick="sendCmd('WAVE')" class="orange">Wave</button>
        <button onclick="sendCmd('CLAP')" class="orange">Clap</button>
    </div>

    <br>

    <div class="grid">
        <div class="card">
            <h2>Right Hand</h2>

            <div class="servo-box">
                <label>R1 <span id="R1_val">90</span></label>
                <input type="range" min="0" max="90" value="90" oninput="updateServo('R1', this.value)">
            </div>

            <div class="servo-box">
                <label>R2 <span id="R2_val">90</span></label>
                <input type="range" min="0" max="180" value="90" oninput="updateServo('R2', this.value)">
            </div>

            <div class="servo-box">
                <label>R3 <span id="R3_val">90</span></label>
                <input type="range" min="90" max="180" value="90" oninput="updateServo('R3', this.value)">
            </div>

            <div class="servo-box">
                <label>R4 <span id="R4_val">0</span></label>
                <input type="range" min="0" max="180" value="0" oninput="updateServo('R4', this.value)">
            </div>

            <div class="servo-box">
                <label>R5 Fingers <span id="R5_val">90</span></label>
                <input type="range" min="90" max="180" value="90" oninput="updateServo('R5', this.value)">
            </div>

            <div class="servo-box">
                <label>R6 Thumb <span id="R6_val">0</span></label>
                <input type="range" min="0" max="90" value="0" oninput="updateServo('R6', this.value)">
            </div>
        </div>

        <div class="card">
            <h2>Left Hand</h2>

            <div class="servo-box">
                <label>L1 <span id="L1_val">90</span></label>
                <input type="range" min="0" max="90" value="90" oninput="updateServo('L1', this.value)">
            </div>

            <div class="servo-box">
                <label>L2 <span id="L2_val">0</span></label>
                <input type="range" min="0" max="180" value="0" oninput="updateServo('L2', this.value)">
            </div>

            <div class="servo-box">
                <label>L3 <span id="L3_val">90</span></label>
                <input type="range" min="0" max="90" value="90" oninput="updateServo('L3', this.value)">
            </div>

            <div class="servo-box">
                <label>L4 <span id="L4_val">180</span></label>
                <input type="range" min="0" max="180" value="180" oninput="updateServo('L4', this.value)">
            </div>

            <div class="servo-box">
                <label>L5 Fingers <span id="L5_val">90</span></label>
                <input type="range" min="90" max="180" value="90" oninput="updateServo('L5', this.value)">
            </div>

            <div class="servo-box">
                <label>L6 Thumb <span id="L6_val">90</span></label>
                <input type="range" min="0" max="90" value="90" oninput="updateServo('L6', this.value)">
            </div>
        </div>
    </div>

    <div class="status" id="status">Ready</div>
</div>

<script>
let timer = null;

function sendCmd(cmd) {
    fetch('/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd })
    })
    .then(res => res.json())
    .then(data => {
        document.getElementById('status').innerText = data.response;
    })
    .catch(err => {
        document.getElementById('status').innerText = err;
    });
}

function updateServo(name, value) {
    document.getElementById(name + '_val').innerText = value;

    clearTimeout(timer);

    timer = setTimeout(() => {
        sendCmd(name + ' ' + value);
    }, 120);
}
</script>

</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/send", methods=["POST"])
def send():
    data = request.get_json()
    command = data.get("command", "")

    response = send_command(command)

    return jsonify({
        "command": command,
        "response": response
    })


@app.route("/ports")
def ports():
    available_ports = []

    for port in serial.tools.list_ports.comports():
        available_ports.append({
            "device": port.device,
            "description": port.description
        })

    return jsonify(available_ports)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)