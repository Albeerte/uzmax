// ================================================================
// UzMAX Professional Firmware - ESP32_HEAD
// Head servos + 84 LED NeoPixel strip
//
// Protocol:
//   PING
//   HEAD SERVO 1 90
//   HEAD SERVO 2 45
//   HEAD LED 255 0 0
//   HEAD LED_OFF
//   HEAD RAINBOW
//
// Extra LED commands:
//   red, green, blue, white, off
//   rainbow, breath, chase, police
//   brightness 0-255
//   color R G B
// ================================================================

#include <Arduino.h>
#include <ESP32Servo.h>
#include <Adafruit_NeoPixel.h>

#define DEVICE_NAME "HEAD"

#define LED_PIN     6
#define LED_COUNT   84
#define BRIGHTNESS  80

#define HEAD_SERVO_1_PIN 13
#define HEAD_SERVO_2_PIN 12

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

Servo headServo1;
Servo headServo2;

int headAngle1 = 90;
int headAngle2 = 90;
uint8_t brightnessValue = BRIGHTNESS;

enum EffectMode {
  EFFECT_NONE,
  EFFECT_RAINBOW,
  EFFECT_BREATH,
  EFFECT_CHASE,
  EFFECT_POLICE
};

EffectMode effectMode = EFFECT_NONE;
unsigned long lastEffectMs = 0;
uint16_t rainbowHue = 0;
int breathPower = 0;
int breathStep = 5;
int chaseIndex = 0;
int policeCycle = 0;
bool policeFlip = false;
bool policeBlank = false;

int clampAngle(int angle) {
  if (angle < 0) return 0;
  if (angle > 180) return 180;
  return angle;
}

void smoothMove(Servo &servo, int &currentAngle, int targetAngle) {
  targetAngle = clampAngle(targetAngle);
  if (targetAngle == currentAngle) return;

  int step = targetAngle > currentAngle ? 1 : -1;
  while (currentAngle != targetAngle) {
    currentAngle += step;
    servo.write(currentAngle);
    delay(8);
  }
}

void stopEffect() {
  effectMode = EFFECT_NONE;
  strip.setBrightness(brightnessValue);
}

void setAll(uint8_t r, uint8_t g, uint8_t b) {
  stopEffect();
  for (int i = 0; i < LED_COUNT; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
  strip.show();
}

void ledOff() {
  stopEffect();
  strip.clear();
  strip.show();
}

bool parseColor(String text, int &r, int &g, int &b) {
  text.trim();
  int firstSpace = text.indexOf(' ');
  int secondSpace = text.indexOf(' ', firstSpace + 1);
  int thirdSpace = text.indexOf(' ', secondSpace + 1);
  if (firstSpace < 0 || secondSpace < 0 || thirdSpace < 0) return false;

  r = constrain(text.substring(firstSpace + 1, secondSpace).toInt(), 0, 255);
  g = constrain(text.substring(secondSpace + 1, thirdSpace).toInt(), 0, 255);
  b = constrain(text.substring(thirdSpace + 1).toInt(), 0, 255);
  return true;
}

void startRainbow() {
  effectMode = EFFECT_RAINBOW;
  rainbowHue = 0;
  lastEffectMs = 0;
}

void startBreath() {
  effectMode = EFFECT_BREATH;
  breathPower = 0;
  breathStep = 5;
  lastEffectMs = 0;
}

void startChase() {
  effectMode = EFFECT_CHASE;
  chaseIndex = 0;
  lastEffectMs = 0;
}

void startPolice() {
  effectMode = EFFECT_POLICE;
  policeCycle = 0;
  policeFlip = false;
  policeBlank = false;
  lastEffectMs = 0;
}

void renderRainbow() {
  for (int i = 0; i < LED_COUNT; i++) {
    int pixelHue = rainbowHue + (i * 65536L / LED_COUNT);
    strip.setPixelColor(i, strip.gamma32(strip.ColorHSV(pixelHue)));
  }
  strip.show();
  rainbowHue += 256;
}

void renderBreath() {
  strip.setBrightness(constrain(breathPower, 0, 255));
  for (int i = 0; i < LED_COUNT; i++) {
    strip.setPixelColor(i, strip.Color(0, 120, 255));
  }
  strip.show();

  breathPower += breathStep;
  if (breathPower >= 255 || breathPower <= 0) breathStep = -breathStep;
}

void renderChase() {
  strip.clear();
  strip.setPixelColor(chaseIndex, strip.Color(255, 80, 0));
  if (chaseIndex > 0) strip.setPixelColor(chaseIndex - 1, strip.Color(63, 20, 0));
  if (chaseIndex > 1) strip.setPixelColor(chaseIndex - 2, strip.Color(31, 10, 0));
  strip.show();
  chaseIndex = (chaseIndex + 1) % LED_COUNT;
}

void renderPolice() {
  if (policeBlank) {
    strip.clear();
    strip.show();
    policeBlank = false;
    policeFlip = !policeFlip;
    policeCycle++;
    if (policeCycle >= 20) ledOff();
    return;
  }

  for (int i = 0; i < LED_COUNT; i++) {
    bool leftHalf = i < LED_COUNT / 2;
    if (leftHalf ^ policeFlip) {
      strip.setPixelColor(i, strip.Color(255, 0, 0));
    } else {
      strip.setPixelColor(i, strip.Color(0, 0, 255));
    }
  }
  strip.show();
  policeBlank = true;
}

void updateEffects() {
  unsigned long now = millis();
  if (effectMode == EFFECT_NONE) return;

  if (effectMode == EFFECT_RAINBOW && now - lastEffectMs >= 5) {
    lastEffectMs = now;
    renderRainbow();
  } else if (effectMode == EFFECT_BREATH && now - lastEffectMs >= 20) {
    lastEffectMs = now;
    renderBreath();
  } else if (effectMode == EFFECT_CHASE && now - lastEffectMs >= 40) {
    lastEffectMs = now;
    renderChase();
  } else if (effectMode == EFFECT_POLICE && now - lastEffectMs >= 120) {
    lastEffectMs = now;
    renderPolice();
  }
}

void printHelp() {
  Serial.println("DEVICE:HEAD");
  Serial.println("Commands:");
  Serial.println("HEAD SERVO 1 90 / HEAD SERVO 2 90");
  Serial.println("HEAD LED 255 0 0 / HEAD LED_OFF / HEAD RAINBOW");
  Serial.println("red, green, blue, white, off, rainbow, breath, chase, police");
  Serial.println("brightness 0-255");
  Serial.println("color R G B");
}

void handleCommand(String rawCommand) {
  rawCommand.trim();
  if (rawCommand.length() == 0) return;

  String upper = rawCommand;
  upper.toUpperCase();
  String lower = rawCommand;
  lower.toLowerCase();

  if (upper == "PING") {
    Serial.println("DEVICE:HEAD");
    return;
  }
  if (upper == "HELP") {
    printHelp();
    return;
  }
  if (upper == "HEAD LED_OFF" || lower == "off") {
    ledOff();
    Serial.println("OK:LED_OFF");
    return;
  }
  if (upper == "HEAD RAINBOW" || lower == "rainbow") {
    startRainbow();
    Serial.println("OK:RAINBOW");
    return;
  }
  if (lower == "red") {
    setAll(255, 0, 0);
    Serial.println("OK:RED");
    return;
  }
  if (lower == "green") {
    setAll(0, 255, 0);
    Serial.println("OK:GREEN");
    return;
  }
  if (lower == "blue") {
    setAll(0, 0, 255);
    Serial.println("OK:BLUE");
    return;
  }
  if (lower == "white") {
    setAll(255, 255, 255);
    Serial.println("OK:WHITE");
    return;
  }
  if (lower == "breath") {
    startBreath();
    Serial.println("OK:BREATH");
    return;
  }
  if (lower == "chase") {
    startChase();
    Serial.println("OK:CHASE");
    return;
  }
  if (lower == "police") {
    startPolice();
    Serial.println("OK:POLICE");
    return;
  }
  if (lower.startsWith("brightness")) {
    int value = constrain(lower.substring(10).toInt(), 0, 255);
    brightnessValue = value;
    strip.setBrightness(brightnessValue);
    strip.show();
    Serial.print("OK:BRIGHTNESS ");
    Serial.println(brightnessValue);
    return;
  }
  if (lower.startsWith("color")) {
    int r, g, b;
    if (parseColor(lower, r, g, b)) {
      setAll(r, g, b);
      Serial.println("OK:COLOR");
    } else {
      Serial.println("ERR:USE color 255 100 0");
    }
    return;
  }
  if (upper.startsWith("HEAD LED ")) {
    String params = upper.substring(9);
    int sp1 = params.indexOf(' ');
    int sp2 = params.indexOf(' ', sp1 + 1);
    if (sp1 < 0 || sp2 < 0) {
      Serial.println("ERR:LED_FORMAT");
      return;
    }
    int r = constrain(params.substring(0, sp1).toInt(), 0, 255);
    int g = constrain(params.substring(sp1 + 1, sp2).toInt(), 0, 255);
    int b = constrain(params.substring(sp2 + 1).toInt(), 0, 255);
    setAll(r, g, b);
    Serial.println("OK:LED");
    return;
  }
  if (upper.startsWith("HEAD SERVO ")) {
    String params = upper.substring(11);
    int sp1 = params.indexOf(' ');
    if (sp1 < 0) {
      Serial.println("ERR:SERVO_FORMAT");
      return;
    }
    int servoNum = params.substring(0, sp1).toInt();
    int angle = params.substring(sp1 + 1).toInt();

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

void setup() {
  Serial.begin(115200);
  delay(500);

  headServo1.setPeriodHertz(50);
  headServo2.setPeriodHertz(50);
  headServo1.attach(HEAD_SERVO_1_PIN, 500, 2500);
  headServo2.attach(HEAD_SERVO_2_PIN, 500, 2500);
  headServo1.write(headAngle1);
  headServo2.write(headAngle2);

  strip.begin();
  strip.setBrightness(brightnessValue);
  strip.clear();
  strip.show();

  printHelp();
}

void loop() {
  updateEffects();
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    handleCommand(command);
  }
}

