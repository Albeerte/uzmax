# UzMAX Robot — Folder Structure
```
uzmax_robot/
├── ESP32_HAND/
│   └── ESP32_HAND.ino          ← Arduino IDE da oching
├── ESP32_HEAD/
│   └── ESP32_HEAD.ino          ← Arduino IDE da oching
├── ESP32_MOVE/
│   └── ESP32_MOVE.ino          ← Arduino IDE da oching
├── rpi/
│   ├── robot_agent.py          ← RPi 5 da ishga tushiring
│   ├── requirements.txt
│   └── known_faces/            ← Tanishlar rasmini shu yerga qo'ying
│       ├── Ali.jpg
│       └── Vali.jpg
└── server/
    ├── main.py                 ← Server FastAPI
    ├── dashboard.html          ← Browser dashboard
    └── requirements.txt
```

---

# Ishga tushirish tartibi

## 1. Arduino Libraries (bir marta)

Arduino IDE → Tools → Manage Libraries:
- `ESP32Servo` by Kevin Harrington
- `Adafruit NeoPixel` by Adafruit

## 2. ESP32 larni yoqish

Har bir `.ino` faylni Arduino IDE da oching va ESP32 ga yuklang.
Serial Monitor da `PING` yozib tekshiring → `DEVICE:HAND` javob kelishi kerak.

## 3. Server o'rnatish

```bash
cd uzmax_robot/server
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

# main.py va dashboard.html dagi YOUR_DOMAIN ni o'zgartiring
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 4. RPi agent o'rnatish

```bash
# RPi 5 da
sudo apt update
sudo apt install -y python3-opencv python3-numpy portaudio19-dev i2c-tools

# I2C yoqish (MLX90640 uchun)
sudo raspi-config → Interface Options → I2C → Enable

cd uzmax_robot/rpi
pip3 install -r requirements.txt --break-system-packages

# robot_agent.py dagi SERVER_WS va SERVER_API ni to'ldiring
python3 robot_agent.py
```

## 5. Dashboard

Brauzerda oching: `https://YOUR_DOMAIN/dashboard`

---

# Serial protocol

| Buyruq             | Ma'nosi                          |
|--------------------|----------------------------------|
| `HAND R 1 90`      | O'ng qo'l 1-servo → 90°         |
| `HAND L 6 120`     | Chap qo'l 6-servo → 120°        |
| `HAND ALL 90`      | Barcha servolar → 90°            |
| `HEAD SERVO 1 90`  | Bosh servo 1 → 90°               |
| `HEAD LED 0 0 255` | LED ko'k rang                    |
| `HEAD LED_OFF`     | LED o'chirish                    |
| `HEAD RAINBOW`     | Rainbow animatsiya               |
| `MOVE FWD 150`     | Oldinga, tezlik 150              |
| `MOVE BACK 150`    | Orqaga, tezlik 150               |
| `MOVE LEFT 120`    | Chap burchak, tezlik 120         |
| `MOVE RIGHT 120`   | O'ng burchak, tezlik 120         |
| `MOVE STOP`        | To'xtatish                       |
| `PING`             | Qurilma o'zini tanishtiradi      |

---

# Pinlar (ESP32_HAND)

| Servo | Qo'l   | GPIO |
|-------|--------|------|
| 1     | O'ng   | 13   |
| 2     | O'ng   | 12   |
| 3     | O'ng   | 14   |
| 4     | O'ng   | 27   |
| 5     | O'ng   | 26   |
| 6     | O'ng   | 25   |
| 1     | Chap   | 33   |
| 2     | Chap   | 32   |
| 3     | Chap   | 23   |
| 4     | Chap   | 22   |
| 5     | Chap   | 21   |
| 6     | Chap   | 19   |

# Pinlar (ESP32_HEAD)

| Qurilma  | GPIO |
|----------|------|
| LED strip| 4    |
| Servo 1  | 13   |
| Servo 2  | 12   |

# Pinlar (ESP32_MOVE)

| Pin           | GPIO (standart, o'zgartiring) |
|---------------|-------------------------------|
| LEFT_FWD      | 13                            |
| LEFT_BACK     | 12                            |
| RIGHT_FWD     | 14                            |
| RIGHT_BACK    | 27                            |
| LEFT_PWM      | 26                            |
| RIGHT_PWM     | 25                            |
