// ============================================================
//  UzMAX MOVE CONTROLLER v4 — ESP32
//  WASD: keydown=start, keyup=stop | S-Curve | 30kg Robot
// ============================================================

// ── Pins ────────────────────────────────────────────────────
#define LEFT_STEP_PIN    18
#define LEFT_DIR_PIN     19
#define LEFT_EN_PIN      21
#define RIGHT_STEP_PIN   22
#define RIGHT_DIR_PIN    23
#define RIGHT_EN_PIN     25

#define ENABLE  LOW
#define DISABLE HIGH

// ── Microstepping 1/8 ───────────────────────────────────────
#define STEPS_PER_REV  1600

// ── Speed delays (microseconds, lower = faster) ─────────────
#define PULSE_START    4000
#define PULSE_SLOW     3000
#define PULSE_FAST      200

// ── Accel ───────────────────────────────────────────────────
#define ACCEL_STEPS    1200
#define DECEL_STEPS    1200
#define DIAG_RATIO     0.65f

// ── KEEPALIVE: UI sends MOVE PING every 80ms ─────────────────
// If no PING in 400ms → auto stop
#define KEEPALIVE_MS    400
#define SERIAL_CHECK     20   // check serial every N steps

// ── State ────────────────────────────────────────────────────
volatile bool stopRequested = false;
bool          motorRunning  = false;
int           currentSpeed  = 60;
unsigned long lastKeepAlive = 0;
String        pendingCmd    = "";

// ============================================================
//  UTILITIES
// ============================================================

int speedToDelay(int spd) {
  spd = constrain(spd, 0, 100);
  return map(spd, 0, 100, PULSE_SLOW, PULSE_FAST);
}

float sCurve(float t) {
  t = constrain(t, 0.0f, 1.0f);
  return t * t * (3.0f - 2.0f * t);
}

int blendDelay(float t, int from, int to) {
  return (int)(from + sCurve(t) * (to - from));
}

// ============================================================
//  MOTOR ENABLE/DISABLE
// ============================================================

void enableAll()  { digitalWrite(LEFT_EN_PIN, ENABLE);  digitalWrite(RIGHT_EN_PIN, ENABLE);  }
void disableAll() { digitalWrite(LEFT_EN_PIN, DISABLE); digitalWrite(RIGHT_EN_PIN, DISABLE); }

// ============================================================
//  SERIAL CHECK — called inside step loops
//  Returns true if should stop
// ============================================================

bool checkSerial() {
  // Keepalive timeout check
  if (motorRunning && millis() - lastKeepAlive > KEEPALIVE_MS) {
    Serial.println("TIMEOUT:STOP");
    stopRequested = true;
    return true;
  }

  while (Serial.available()) {
    String incoming = Serial.readStringUntil('\n');
    incoming.trim();
    if (incoming.length() == 0) continue;

    if (incoming == "MOVE STOP" || incoming == "STOP") {
      stopRequested = true;
      return true;
    }
    if (incoming == "MOVE PING") {
      lastKeepAlive = millis();
      Serial.println("PONG");    // confirm ping received
      return false;
    }
    if (incoming.startsWith("MOVE SPEED ")) {
      currentSpeed = constrain(incoming.substring(11).toInt(), 0, 100);
      Serial.print("OK:SPEED "); Serial.println(currentSpeed);
      return false;
    }
    // New movement command → queue it and stop current
    pendingCmd    = incoming;
    stopRequested = true;
    return true;
  }
  return false;
}

// ============================================================
//  PULSE HELPERS
// ============================================================

inline void pulsePin(int pin, int d) {
  digitalWrite(pin, HIGH); delayMicroseconds(d);
  digitalWrite(pin, LOW);  delayMicroseconds(d);
}

inline void pulseBoth(int d) {
  digitalWrite(LEFT_STEP_PIN,  HIGH);
  digitalWrite(RIGHT_STEP_PIN, HIGH);
  delayMicroseconds(d);
  digitalWrite(LEFT_STEP_PIN,  LOW);
  digitalWrite(RIGHT_STEP_PIN, LOW);
  delayMicroseconds(d);
}

// ============================================================
//  CONTINUOUS BOTH MOTORS (keydown → hold → keyup → stop)
// ============================================================

void continuousBoth(bool leftFwd, bool rightFwd, int targetDelay) {
  enableAll();
  motorRunning  = true;
  stopRequested = false;
  lastKeepAlive = millis();

  digitalWrite(LEFT_DIR_PIN,  leftFwd  ? HIGH : LOW);
  digitalWrite(RIGHT_DIR_PIN, rightFwd ? HIGH : LOW);

  int  curDelay   = PULSE_START;
  int  accelStep  = 0;
  int  decelStep  = 0;
  int  stepCount  = 0;
  bool deceling   = false;

  while (true) {
    // Accelerate
    if (!deceling) {
      accelStep++;
      float t = constrain((float)accelStep / ACCEL_STEPS, 0.0f, 1.0f);
      curDelay = blendDelay(t, PULSE_START, targetDelay);
    }
    // Decelerate
    if (stopRequested) deceling = true;
    if (deceling) {
      decelStep++;
      float t = constrain((float)decelStep / DECEL_STEPS, 0.0f, 1.0f);
      curDelay = blendDelay(t, targetDelay, PULSE_START);
      if (curDelay >= PULSE_START) break;
    }

    pulseBoth(curDelay);
    if (++stepCount >= SERIAL_CHECK) { stepCount = 0; checkSerial(); }
  }

  motorRunning = false;
  disableAll();
  Serial.println("OK:STOPPED");
}

// ============================================================
//  CONTINUOUS SINGLE MOTOR (turn pivot)
// ============================================================

void continuousSingle(int stepPin, int dirPin, bool dir, int targetDelay) {
  enableAll();
  motorRunning  = true;
  stopRequested = false;
  lastKeepAlive = millis();

  digitalWrite(dirPin, dir ? HIGH : LOW);

  int  curDelay  = PULSE_START;
  int  accelStep = 0;
  int  decelStep = 0;
  int  stepCount = 0;
  bool deceling  = false;

  while (true) {
    if (!deceling) {
      accelStep++;
      float t = constrain((float)accelStep / ACCEL_STEPS, 0.0f, 1.0f);
      curDelay = blendDelay(t, PULSE_START, targetDelay);
    }
    if (stopRequested) deceling = true;
    if (deceling) {
      decelStep++;
      float t = constrain((float)decelStep / DECEL_STEPS, 0.0f, 1.0f);
      curDelay = blendDelay(t, targetDelay, PULSE_START);
      if (curDelay >= PULSE_START) break;
    }
    pulsePin(stepPin, curDelay);
    if (++stepCount >= SERIAL_CHECK) { stepCount = 0; checkSerial(); }
  }

  motorRunning = false;
  disableAll();
  Serial.println("OK:STOPPED");
}

// ============================================================
//  DIAGONAL (one wheel slower)
// ============================================================

void continuousDiagonal(bool fwd, bool curveLeft, int targetDelay) {
  enableAll();
  motorRunning  = true;
  stopRequested = false;
  lastKeepAlive = millis();

  int outerTarget = targetDelay;
  int innerTarget = (int)(targetDelay / DIAG_RATIO);

  digitalWrite(LEFT_DIR_PIN,  fwd ? HIGH : LOW);
  digitalWrite(RIGHT_DIR_PIN, fwd ? LOW  : HIGH);

  int  outerDelay = PULSE_START;
  int  innerDelay = PULSE_START;
  int  accelStep  = 0;
  int  decelStep  = 0;
  int  stepCount  = 0;
  bool deceling   = false;
  int  innerAcc   = 0;

  while (true) {
    if (!deceling) {
      accelStep++;
      float t    = constrain((float)accelStep / ACCEL_STEPS, 0.0f, 1.0f);
      outerDelay = blendDelay(t, PULSE_START, outerTarget);
      innerDelay = blendDelay(t, PULSE_START, innerTarget);
    }
    if (stopRequested) deceling = true;
    if (deceling) {
      decelStep++;
      float t    = constrain((float)decelStep / DECEL_STEPS, 0.0f, 1.0f);
      outerDelay = blendDelay(t, outerTarget, PULSE_START);
      innerDelay = blendDelay(t, innerTarget, PULSE_START);
      if (outerDelay >= PULSE_START) break;
    }

    if (curveLeft) {
      digitalWrite(RIGHT_STEP_PIN, HIGH);
      innerAcc += 1000;
      if (innerAcc >= (int)(DIAG_RATIO * 1000)) {
        digitalWrite(LEFT_STEP_PIN, HIGH);
        innerAcc -= (int)(DIAG_RATIO * 1000);
      }
    } else {
      digitalWrite(LEFT_STEP_PIN, HIGH);
      innerAcc += 1000;
      if (innerAcc >= (int)(DIAG_RATIO * 1000)) {
        digitalWrite(RIGHT_STEP_PIN, HIGH);
        innerAcc -= (int)(DIAG_RATIO * 1000);
      }
    }
    delayMicroseconds(outerDelay);
    digitalWrite(LEFT_STEP_PIN, LOW); digitalWrite(RIGHT_STEP_PIN, LOW);
    delayMicroseconds(outerDelay);

    if (++stepCount >= SERIAL_CHECK) { stepCount = 0; checkSerial(); }
  }

  motorRunning = false;
  disableAll();
  Serial.println("OK:STOPPED");
}

// ============================================================
//  COMMAND PARSER
// ============================================================

void handleCommand(String input) {
  int pulseDelay = speedToDelay(currentSpeed);
  stopRequested  = false;
  pendingCmd     = "";

  Serial.print("CMD:"); Serial.println(input);  // always echo

  if (input == "MOVE STOP" || input == "STOP") {
    motorRunning  = false;
    stopRequested = false;
    disableAll();
    Serial.println("OK:STOPPED");
    return;
  }
  if (input == "MOVE PING") {
    lastKeepAlive = millis();
    Serial.println("PONG");
    return;
  }
  if (input.startsWith("MOVE SPEED ")) {
    currentSpeed = constrain(input.substring(11).toInt(), 0, 100);
    Serial.print("OK:SPEED "); Serial.println(currentSpeed);
    return;
  }

  // Parse direction
  String dir = "";
  int    steps = 0;

  if      (input == "W") dir = "FWD";
  else if (input == "S") dir = "BACK";
  else if (input == "A") dir = "LEFT";
  else if (input == "D") dir = "RIGHT";
  else if (input == "Q") dir = "CCW";
  else if (input == "E") dir = "CW";
  else if (input.startsWith("MOVE ")) {
    String rest = input.substring(5);
    int sp = rest.indexOf(' ');
    dir   = (sp == -1) ? rest : rest.substring(0, sp);
    steps = (sp == -1) ? 0    : rest.substring(sp + 1).toInt();
  }
  else { Serial.println("ERR:UNKNOWN"); return; }

  // Execute
  if      (dir == "FWD")        continuousBoth(true, false, pulseDelay);
  else if (dir == "BACK")       continuousBoth(false, true,  pulseDelay);
  else if (dir == "LEFT")       continuousSingle(LEFT_STEP_PIN,  LEFT_DIR_PIN,  false, pulseDelay);
  else if (dir == "RIGHT")      continuousSingle(RIGHT_STEP_PIN, RIGHT_DIR_PIN, false, pulseDelay);
  else if (dir == "CW")         continuousBoth(true,  true,  pulseDelay);
  else if (dir == "CCW")        continuousBoth(false, false, pulseDelay);
  else if (dir == "FWD_LEFT")   continuousDiagonal(true,  true,  pulseDelay);
  else if (dir == "FWD_RIGHT")  continuousDiagonal(true,  false, pulseDelay);
  else if (dir == "BACK_LEFT")  continuousDiagonal(false, true,  pulseDelay);
  else if (dir == "BACK_RIGHT") continuousDiagonal(false, false, pulseDelay);
  else                          Serial.println("ERR:UNKNOWN_DIR");

  // Chain pending command
  if (pendingCmd.length() > 0) {
    String next = pendingCmd;
    pendingCmd  = "";
    handleCommand(next);
  }
}

// ============================================================
//  SETUP & LOOP
// ============================================================

void setup() {
  Serial.begin(115200);

  pinMode(LEFT_STEP_PIN,  OUTPUT); pinMode(LEFT_DIR_PIN,  OUTPUT); pinMode(LEFT_EN_PIN,  OUTPUT);
  pinMode(RIGHT_STEP_PIN, OUTPUT); pinMode(RIGHT_DIR_PIN, OUTPUT); pinMode(RIGHT_EN_PIN, OUTPUT);

  digitalWrite(LEFT_STEP_PIN,  LOW); digitalWrite(LEFT_DIR_PIN,  LOW);
  digitalWrite(RIGHT_STEP_PIN, LOW); digitalWrite(RIGHT_DIR_PIN, LOW);
  disableAll();

  Serial.println("MOVE v4 READY");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0) handleCommand(cmd);
  }
}