// ================================================================
//  UzMAX Robot — ESP32_MOVE
//  Dual DC motor driver with PWM speed control
//  Protocol:
//    MOVE FWD 150    → forward at speed 150
//    MOVE BACK 150   → backward at speed 150
//    MOVE LEFT 120   → left spin at speed 120
//    MOVE RIGHT 120  → right spin at speed 120
//    MOVE STOP       → stop all motors
//    PING            → responds DEVICE:MOVE
//
//  CHANGE THE PINS BELOW to match your actual motor driver wiring.
// ================================================================

#include <Arduino.h>

#define DEVICE_NAME "MOVE"

// ── Motor driver direction pins ───────────────────────────────────
// Left motor
#define LEFT_FWD_PIN    13
#define LEFT_BACK_PIN   12

// Right motor
#define RIGHT_FWD_PIN   14
#define RIGHT_BACK_PIN  27

// ── PWM speed pins ────────────────────────────────────────────────
#define LEFT_PWM_PIN    26
#define RIGHT_PWM_PIN   25

// ── LEDC PWM settings ─────────────────────────────────────────────
#define PWM_FREQ        1000
#define PWM_RESOLUTION  8          // 0–255
#define LEFT_CHANNEL    0
#define RIGHT_CHANNEL   1

// ── Helpers ──────────────────────────────────────────────────────
int clampSpeed(int v) {
  if (v < 0)   return 0;
  if (v > 255) return 255;
  return v;
}

void setMotorSpeed(int leftSpeed, int rightSpeed) {
  ledcWrite(LEFT_CHANNEL,  clampSpeed(leftSpeed));
  ledcWrite(RIGHT_CHANNEL, clampSpeed(rightSpeed));
}

void stopRobot() {
  digitalWrite(LEFT_FWD_PIN,   LOW);
  digitalWrite(LEFT_BACK_PIN,  LOW);
  digitalWrite(RIGHT_FWD_PIN,  LOW);
  digitalWrite(RIGHT_BACK_PIN, LOW);
  setMotorSpeed(0, 0);
}

void forward(int speed) {
  setMotorSpeed(speed, speed);
  digitalWrite(LEFT_FWD_PIN,   HIGH);
  digitalWrite(LEFT_BACK_PIN,  LOW);
  digitalWrite(RIGHT_FWD_PIN,  HIGH);
  digitalWrite(RIGHT_BACK_PIN, LOW);
}

void backward(int speed) {
  setMotorSpeed(speed, speed);
  digitalWrite(LEFT_FWD_PIN,   LOW);
  digitalWrite(LEFT_BACK_PIN,  HIGH);
  digitalWrite(RIGHT_FWD_PIN,  LOW);
  digitalWrite(RIGHT_BACK_PIN, HIGH);
}

void leftTurn(int speed) {
  setMotorSpeed(speed, speed);
  digitalWrite(LEFT_FWD_PIN,   LOW);
  digitalWrite(LEFT_BACK_PIN,  HIGH);
  digitalWrite(RIGHT_FWD_PIN,  HIGH);
  digitalWrite(RIGHT_BACK_PIN, LOW);
}

void rightTurn(int speed) {
  setMotorSpeed(speed, speed);
  digitalWrite(LEFT_FWD_PIN,   HIGH);
  digitalWrite(LEFT_BACK_PIN,  LOW);
  digitalWrite(RIGHT_FWD_PIN,  LOW);
  digitalWrite(RIGHT_BACK_PIN, HIGH);
}

// ── Setup ─────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(1000);

  // Direction pins
  pinMode(LEFT_FWD_PIN,   OUTPUT);
  pinMode(LEFT_BACK_PIN,  OUTPUT);
  pinMode(RIGHT_FWD_PIN,  OUTPUT);
  pinMode(RIGHT_BACK_PIN, OUTPUT);

  // LEDC PWM channels
  ledcSetup(LEFT_CHANNEL,  PWM_FREQ, PWM_RESOLUTION);
  ledcSetup(RIGHT_CHANNEL, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(LEFT_PWM_PIN,  LEFT_CHANNEL);
  ledcAttachPin(RIGHT_PWM_PIN, RIGHT_CHANNEL);

  stopRobot();

  Serial.println("DEVICE:MOVE");
  Serial.println("READY");
}

// ── Main loop ─────────────────────────────────────────────────────
void loop() {
  if (!Serial.available()) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  // ── PING ──────────────────────────────────────────────────────
  if (cmd == "PING") {
    Serial.println("DEVICE:MOVE");
    return;
  }

  // ── Validate prefix ───────────────────────────────────────────
  if (!cmd.startsWith("MOVE")) {
    Serial.println("ERR:NOT_MOVE_COMMAND");
    return;
  }

  // ── MOVE STOP ─────────────────────────────────────────────────
  if (cmd == "MOVE STOP") {
    stopRobot();
    Serial.println("OK:STOP");
    return;
  }

  // ── MOVE <action> <speed> ─────────────────────────────────────
  int p1 = cmd.indexOf(' ');
  int p2 = cmd.indexOf(' ', p1 + 1);

  if (p1 < 0 || p2 < 0) {
    Serial.println("ERR:MOVE_FORMAT");
    return;
  }

  String action = cmd.substring(p1 + 1, p2);
  int speed     = clampSpeed(cmd.substring(p2 + 1).toInt());

  if (action == "FWD") {
    forward(speed);
    Serial.println("OK:FWD");
  } else if (action == "BACK") {
    backward(speed);
    Serial.println("OK:BACK");
  } else if (action == "LEFT") {
    leftTurn(speed);
    Serial.println("OK:LEFT");
  } else if (action == "RIGHT") {
    rightTurn(speed);
    Serial.println("OK:RIGHT");
  } else {
    Serial.println("ERR:UNKNOWN_MOVE");
  }
}
