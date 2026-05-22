// ================================================================
//  AXON HEAD ESP32
//  360° Servo (GPIO 17) + 84 LED Strip (GPIO 4)
//
//  Libraries required (install via Arduino Library Manager):
//    • ESP32Servo       by Kevin Harrington
//    • Adafruit NeoPixel by Adafruit
//
//  Serial Monitor:
//    Baud rate  : 115200
//    Line ending: Newline
//
//  Commands:
//    cw 1000          → clockwise 1 second
//    ccw 1000         → counter-clockwise 1 second
//    run 80 1500      → value 80 for 1.5 seconds
//    stop             → stop servo
//    stop 92          → change stop value (calibrate)
//
//    led 255 0 0      → set all LEDs red
//    led 0 255 0      → green
//    led 0 0 255      → blue
//    off              → LEDs off
//    rainbow          → rainbow animation (send any command to abort)
//    brightness 80    → set brightness (0–255)
//
//  Wiring:
//    Servo signal → GPIO 17
//    LED data     → GPIO 4
//    LED 12V+     → 12V supply
//    LED GND      → 12V GND (common GND with ESP32 & Servo)
//    Servo VCC    → 6V supply
//    ESP32 VCC    → 5V supply (USB or regulator)
// ================================================================

#include <ESP32Servo.h>
#include <Adafruit_NeoPixel.h>

// ─── Pins ──────────────────────────────────────────────────────
#define SERVO_PIN  17
#define LED_PIN     4

// ─── LED strip ─────────────────────────────────────────────────
#define LED_COUNT  84
Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

// ─── Servo ─────────────────────────────────────────────────────
Servo servo360;

// 360° servo neutral (stop) pulse width varies per unit.
// Default 90. If servo drifts, calibrate with: stop 88 … stop 95
int STOP_VALUE = 90;
int CW_VALUE   = 0;    // full speed clockwise
int CCW_VALUE  = 180;  // full speed counter-clockwise

// ─── LED state ─────────────────────────────────────────────────
int brightnessValue = 120;

// ───────────────────────────────────────────────────────────────
//  UTILITIES
// ───────────────────────────────────────────────────────────────
int clamp(int value, int lo, int hi) {
  if (value < lo) return lo;
  if (value > hi) return hi;
  return value;
}

// ───────────────────────────────────────────────────────────────
//  SERVO FUNCTIONS
// ───────────────────────────────────────────────────────────────
void stopServo() {
  servo360.write(STOP_VALUE);
  Serial.println("OK STOP");
}

// Rotate at *value* for *timeMs* milliseconds, then stop.
void rotateForTime(int value, int timeMs) {
  value  = clamp(value,  0,    180);
  timeMs = clamp(timeMs, 0, 30000);

  servo360.write(value);

  Serial.print("OK RUN value=");
  Serial.print(value);
  Serial.print(" time=");
  Serial.print(timeMs);
  Serial.println("ms");

  delay(timeMs);

  stopServo();
}

// ───────────────────────────────────────────────────────────────
//  LED FUNCTIONS
// ───────────────────────────────────────────────────────────────
void setLED(int r, int g, int b) {
  r = clamp(r, 0, 255);
  g = clamp(g, 0, 255);
  b = clamp(b, 0, 255);

  for (int i = 0; i < LED_COUNT; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
  strip.show();

  Serial.print("OK LED ");
  Serial.print(r); Serial.print(" ");
  Serial.print(g); Serial.print(" ");
  Serial.println(b);
}

void ledOff() {
  setLED(0, 0, 0);
  Serial.println("OK LED OFF");
}

// One full rainbow cycle. Aborts if a serial byte arrives.
void rainbowOnce() {
  Serial.println("OK RAINBOW START");
  for (long hue = 0; hue < 65536; hue += 512) {
    if (Serial.available()) {
      Serial.println("OK RAINBOW STOPPED");
      return;
    }
    for (int i = 0; i < LED_COUNT; i++) {
      int pixelHue = hue + (i * 65536L / LED_COUNT);
      strip.setPixelColor(i, strip.gamma32(strip.ColorHSV(pixelHue)));
    }
    strip.show();
    delay(15);
  }
  Serial.println("OK RAINBOW DONE");
}

// ───────────────────────────────────────────────────────────────
//  COMMAND PARSER
// ───────────────────────────────────────────────────────────────
void handleCommand(String cmd) {
  cmd.trim();
  cmd.toLowerCase();
  if (cmd.length() == 0) return;

  // ── SERVO COMMANDS ───────────────────────────────────────────

  // stop
  if (cmd == "stop") {
    stopServo();
    return;
  }

  // stop <value>   e.g. stop 92
  if (cmd.startsWith("stop ")) {
    STOP_VALUE = clamp(cmd.substring(5).toInt(), 0, 180);
    stopServo();
    Serial.print("OK NEW STOP VALUE = ");
    Serial.println(STOP_VALUE);
    return;
  }

  // cw <ms>   e.g. cw 1000
  if (cmd.startsWith("cw ")) {
    int ms = cmd.substring(3).toInt();
    rotateForTime(CW_VALUE, ms);
    return;
  }

  // ccw <ms>   e.g. ccw 1000
  if (cmd.startsWith("ccw ")) {
    int ms = cmd.substring(4).toInt();
    rotateForTime(CCW_VALUE, ms);
    return;
  }

  // run <value> <ms>   e.g. run 80 1500
  if (cmd.startsWith("run ")) {
    int sp1 = cmd.indexOf(' ');
    int sp2 = cmd.indexOf(' ', sp1 + 1);
    if (sp2 == -1) {
      Serial.println("ERROR use: run 80 1500");
      return;
    }
    int val = cmd.substring(sp1 + 1, sp2).toInt();
    int ms  = cmd.substring(sp2 + 1).toInt();
    rotateForTime(val, ms);
    return;
  }

  // ── LED COMMANDS ─────────────────────────────────────────────

  // led <r> <g> <b>   e.g. led 255 0 0
  if (cmd.startsWith("led ")) {
    int sp1 = cmd.indexOf(' ');
    int sp2 = cmd.indexOf(' ', sp1 + 1);
    int sp3 = cmd.indexOf(' ', sp2 + 1);
    if (sp2 == -1 || sp3 == -1) {
      Serial.println("ERROR use: led 255 0 0");
      return;
    }
    int r = cmd.substring(sp1 + 1, sp2).toInt();
    int g = cmd.substring(sp2 + 1, sp3).toInt();
    int b = cmd.substring(sp3 + 1).toInt();
    setLED(r, g, b);
    return;
  }

  // off
  if (cmd == "off") {
    ledOff();
    return;
  }

  // rainbow
  if (cmd == "rainbow") {
    rainbowOnce();
    return;
  }

  // brightness <0-255>   e.g. brightness 80
  if (cmd.startsWith("brightness ")) {
    brightnessValue = clamp(cmd.substring(11).toInt(), 0, 255);
    strip.setBrightness(brightnessValue);
    strip.show();
    Serial.print("OK BRIGHTNESS = ");
    Serial.println(brightnessValue);
    return;
  }

  // Unknown
  Serial.println("ERROR UNKNOWN COMMAND");
  Serial.println("Servo : cw 1000 | ccw 1000 | run 80 1500 | stop | stop 92");
  Serial.println("LED   : led 255 0 0 | off | rainbow | brightness 80");
}

// ───────────────────────────────────────────────────────────────
//  SETUP
// ───────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(1000);

  // Servo init
  ESP32PWM::allocateTimer(0);
  servo360.setPeriodHertz(50);
  servo360.attach(SERVO_PIN, 500, 2500);
  stopServo();

  // LED strip init
  strip.begin();
  strip.setBrightness(brightnessValue);
  strip.show();

  // Startup blink: blue flash → off
  setLED(0, 50, 255);
  delay(300);
  ledOff();

  Serial.println("=================================");
  Serial.println("  AXON HEAD ESP32 READY");
  Serial.println("=================================");
  Serial.println("Servo : cw 1000 | ccw 1000");
  Serial.println("        run 80 1500 | stop | stop 92");
  Serial.println("LED   : led 255 0 0 | off");
  Serial.println("        rainbow | brightness 80");
  Serial.println("=================================");
}

// ───────────────────────────────────────────────────────────────
//  LOOP
// ───────────────────────────────────────────────────────────────
void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    handleCommand(command);
  }
}
