// ================================================================
//  UzMAX Robot — ESP32_HEAD
//  2 Standard servos (head tilt/pan) + 84-LED NeoPixel strip
//  Protocol:
//    HEAD SERVO 1 90      → Servo #1 to 90°
//    HEAD SERVO 2 45      → Servo #2 to 45°
//    HEAD LED 255 0 0     → Set all LEDs to R,G,B
//    HEAD LED_OFF         → Turn all LEDs off
//    HEAD RAINBOW         → Rainbow animation (non-blocking start)
//    PING                 → responds DEVICE:HEAD
// ================================================================

#include <Arduino.h>
#include <ESP32Servo.h>
#include <Adafruit_NeoPixel.h>

#define DEVICE_NAME "HEAD"

// ── Pin assignments ──────────────────────────────────────────────
#define LED_PIN           4
#define LED_COUNT         84

#define HEAD_SERVO_1_PIN  13
#define HEAD_SERVO_2_PIN  12

// ── Objects ───────────────────────────────────────────────────────
Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

Servo headServo1;
Servo headServo2;

int headAngle1 = 90;
int headAngle2 = 90;

bool rainbowRunning = false;
uint16_t rainbowHue = 0;

// ── Helpers ──────────────────────────────────────────────────────
int clampAngle(int angle) {
  if (angle < 0)   return 0;
  if (angle > 180) return 180;
  return angle;
}

void smoothMove(Servo &servo, int &currentAngle, int targetAngle) {
  targetAngle = clampAngle(targetAngle);

  if (targetAngle > currentAngle) {
    for (int a = currentAngle; a <= targetAngle; a++) {
      servo.write(a);
      delay(8);
    }
  } else {
    for (int a = currentAngle; a >= targetAngle; a--) {
      servo.write(a);
      delay(8);
    }
  }

  currentAngle = targetAngle;
}

void setLedColor(int r, int g, int b) {
  rainbowRunning = false;
  r = constrain(r, 0, 255);
  g = constrain(g, 0, 255);
  b = constrain(b, 0, 255);

  for (int i = 0; i < LED_COUNT; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }

  strip.show();
}

void ledOff() {
  rainbowRunning = false;
  strip.clear();
  strip.show();
}

// ── Setup ─────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(1000);

  headServo1.setPeriodHertz(50);
  headServo2.setPeriodHertz(50);

  headServo1.attach(HEAD_SERVO_1_PIN, 500, 2500);
  headServo2.attach(HEAD_SERVO_2_PIN, 500, 2500);

  headServo1.write(headAngle1);
  headServo2.write(headAngle2);

  strip.begin();
  strip.setBrightness(80);
  strip.clear();
  strip.show();

  // Boot indication: brief cyan flash
  setLedColor(0, 200, 200);
  delay(400);
  ledOff();

  Serial.println("DEVICE:HEAD");
  Serial.println("READY");
}

// ── Main loop ─────────────────────────────────────────────────────
void loop() {
  // Rainbow animation (non-blocking)
  if (rainbowRunning) {
    strip.rainbow(rainbowHue);
    strip.show();
    rainbowHue += 256;
  }

  if (!Serial.available()) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  // ── PING ──────────────────────────────────────────────────────
  if (cmd == "PING") {
    Serial.println("DEVICE:HEAD");
    return;
  }

  // ── HEAD LED_OFF ──────────────────────────────────────────────
  if (cmd == "HEAD LED_OFF") {
    ledOff();
    Serial.println("OK:LED_OFF");
    return;
  }

  // ── HEAD RAINBOW ──────────────────────────────────────────────
  if (cmd == "HEAD RAINBOW") {
    rainbowRunning = true;
    rainbowHue     = 0;
    Serial.println("OK:RAINBOW");
    return;
  }

  // ── HEAD LED R G B ────────────────────────────────────────────
  // "HEAD LED 255 120 0"
  if (cmd.startsWith("HEAD LED ")) {
    // Skip "HEAD LED " (9 chars)
    String params = cmd.substring(9);
    int sp1 = params.indexOf(' ');
    int sp2 = params.indexOf(' ', sp1 + 1);

    if (sp1 < 0 || sp2 < 0) {
      Serial.println("ERR:LED_FORMAT");
      return;
    }

    int r = params.substring(0, sp1).toInt();
    int g = params.substring(sp1 + 1, sp2).toInt();
    int b = params.substring(sp2 + 1).toInt();

    setLedColor(r, g, b);
    Serial.println("OK:LED");
    return;
  }

  // ── HEAD SERVO N angle ────────────────────────────────────────
  // "HEAD SERVO 1 90"
  if (cmd.startsWith("HEAD SERVO ")) {
    // Skip "HEAD SERVO " (11 chars)
    String params = cmd.substring(11);
    int sp1 = params.indexOf(' ');

    if (sp1 < 0) {
      Serial.println("ERR:SERVO_FORMAT");
      return;
    }

    int servoNum = params.substring(0, sp1).toInt();
    int angle    = params.substring(sp1 + 1).toInt();

    if (servoNum == 1) {
      smoothMove(headServo1, headAngle1, angle);
      Serial.println("OK:HEAD_SERVO_1");
    } else if (servoNum == 2) {
      smoothMove(headServo2, headAngle2, angle);
      Serial.println("OK:HEAD_SERVO_2");
    } else {
      Serial.println("ERR:HEAD_SERVO_NUM");
    }

    return;
  }

  Serial.println("ERR:UNKNOWN_HEAD_COMMAND");
}
