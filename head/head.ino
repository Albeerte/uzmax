#include <Arduino.h>
#include <ESP32Servo.h>
#include <Adafruit_NeoPixel.h>

#define DEVICE_NAME "HEAD"
#define BAUD_RATE 115200

// Change these pins if your wiring is different.
#define LED_PIN 6
#define LED_COUNT 84
#define LED_BRIGHTNESS 80

#define HEAD_SERVO_1_PIN 17
#define HEAD_SERVO_2_PIN 16

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
Servo headServo1;
Servo headServo2;

int headAngle1 = 90;
int headAngle2 = 90;
uint8_t brightnessValue = LED_BRIGHTNESS;

int clampAngle(int angle) {
  if (angle < 0) return 0;
  if (angle > 180) return 180;
  return angle;
}

void smoothServoMove(Servo &servo, int &currentAngle, int targetAngle) {
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

void setAll(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < LED_COUNT; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
  strip.show();
}

void ledOff() {
  strip.clear();
  strip.show();
}

void rainbow(int waitMs) {
  for (long hue = 0; hue < 65536; hue += 256) {
    if (Serial.available()) return;
    for (int i = 0; i < LED_COUNT; i++) {
      int pixelHue = hue + (i * 65536L / LED_COUNT);
      strip.setPixelColor(i, strip.gamma32(strip.ColorHSV(pixelHue)));
    }
    strip.show();
    delay(waitMs);
  }
}

void breathingEffect(uint8_t r, uint8_t g, uint8_t b) {
  for (int power = 0; power <= 255; power += 5) {
    if (Serial.available()) return;
    strip.setBrightness(power);
    setAll(r, g, b);
    delay(20);
  }
  for (int power = 255; power >= 0; power -= 5) {
    if (Serial.available()) return;
    strip.setBrightness(power);
    setAll(r, g, b);
    delay(20);
  }
  strip.setBrightness(brightnessValue);
  setAll(r, g, b);
}

void colorChase(uint8_t r, uint8_t g, uint8_t b, int waitMs) {
  for (int i = 0; i < LED_COUNT; i++) {
    if (Serial.available()) return;
    strip.clear();
    strip.setPixelColor(i, strip.Color(r, g, b));
    if (i > 0) strip.setPixelColor(i - 1, strip.Color(r / 4, g / 4, b / 4));
    if (i > 1) strip.setPixelColor(i - 2, strip.Color(r / 8, g / 8, b / 8));
    strip.show();
    delay(waitMs);
  }
}

void policeEffect() {
  for (int cycle = 0; cycle < 10; cycle++) {
    if (Serial.available()) return;
    for (int i = 0; i < LED_COUNT; i++) {
      strip.setPixelColor(i, i < LED_COUNT / 2 ? strip.Color(255, 0, 0) : strip.Color(0, 0, 255));
    }
    strip.show();
    delay(150);
    ledOff();
    delay(100);
    for (int i = 0; i < LED_COUNT; i++) {
      strip.setPixelColor(i, i < LED_COUNT / 2 ? strip.Color(0, 0, 255) : strip.Color(255, 0, 0));
    }
    strip.show();
    delay(150);
    ledOff();
    delay(100);
  }
}

bool parseThreeInts(String text, int startIndex, int &a, int &b, int &c) {
  text = text.substring(startIndex);
  text.trim();
  int p1 = text.indexOf(' ');
  int p2 = text.indexOf(' ', p1 + 1);
  if (p1 < 0 || p2 < 0) return false;
  a = constrain(text.substring(0, p1).toInt(), 0, 255);
  b = constrain(text.substring(p1 + 1, p2).toInt(), 0, 255);
  c = constrain(text.substring(p2 + 1).toInt(), 0, 255);
  return true;
}

bool isIntegerCommand(String command) {
  if (command.length() == 0) return false;
  for (int i = 0; i < command.length(); i++) {
    if (!isDigit(command[i])) return false;
  }
  return true;
}

void printReady() {
  Serial.println("DEVICE:HEAD");
  Serial.println("HEAD READY");
  Serial.println("Commands:");
  Serial.println("HEAD SERVO 1 90");
  Serial.println("HEAD LED 255 0 0");
  Serial.println("HEAD LED_OFF");
  Serial.println("HEAD RAINBOW");
  Serial.println("Legacy: color 255 0 0 / red / green / blue / off / rainbow");
}

void handleCommand(String command) {
  command.trim();
  if (command.length() == 0) return;

  String lower = command;
  lower.toLowerCase();
  String upper = command;
  upper.toUpperCase();

  if (upper == "PING") {
    Serial.println("DEVICE:HEAD");
    return;
  }

  if (upper.startsWith("HEAD SERVO ")) {
    int p = command.indexOf(' ', 11);
    if (p < 0) {
      Serial.println("ERR:SERVO_FORMAT");
      return;
    }
    int servoNum = command.substring(11, p).toInt();
    int angle = command.substring(p + 1).toInt();
    if (servoNum == 1) {
      smoothServoMove(headServo1, headAngle1, angle);
      Serial.println("OK:HEAD_SERVO_1");
    } else if (servoNum == 2) {
      smoothServoMove(headServo2, headAngle2, angle);
      Serial.println("OK:HEAD_SERVO_2");
    } else {
      Serial.println("ERR:HEAD_SERVO_NUM");
    }
    return;
  }

  if (upper.startsWith("HEAD LED ")) {
    int r, g, b;
    if (!parseThreeInts(command, 9, r, g, b)) {
      Serial.println("ERR:LED_FORMAT");
      return;
    }
    setAll(r, g, b);
    Serial.println("OK:LED");
    return;
  }

  if (upper == "HEAD LED_OFF") {
    ledOff();
    Serial.println("OK:LED_OFF");
    return;
  }

  if (upper == "HEAD RAINBOW") {
    rainbow(5);
    Serial.println("OK:RAINBOW");
    return;
  }

  // Legacy commands from your LED-only sketch.
  if (lower == "red") {
    setAll(255, 0, 0);
    Serial.println("OK:RED");
  } else if (lower == "green") {
    setAll(0, 255, 0);
    Serial.println("OK:GREEN");
  } else if (lower == "blue") {
    setAll(0, 0, 255);
    Serial.println("OK:BLUE");
  } else if (lower == "white") {
    setAll(255, 255, 255);
    Serial.println("OK:WHITE");
  } else if (lower == "off") {
    ledOff();
    Serial.println("OK:OFF");
  } else if (lower == "rainbow") {
    rainbow(5);
    Serial.println("OK:RAINBOW");
  } else if (lower == "breath") {
    breathingEffect(0, 120, 255);
    Serial.println("OK:BREATH");
  } else if (lower == "chase") {
    colorChase(255, 80, 0, 40);
    Serial.println("OK:CHASE");
  } else if (lower == "police") {
    policeEffect();
    Serial.println("OK:POLICE");
  } else if (lower.startsWith("brightness")) {
    int value = constrain(command.substring(10).toInt(), 0, 255);
    brightnessValue = value;
    strip.setBrightness(brightnessValue);
    strip.show();
    Serial.print("OK:BRIGHTNESS ");
    Serial.println(brightnessValue);
  } else if (lower.startsWith("color ")) {
    int r, g, b;
    if (!parseThreeInts(command, 6, r, g, b)) {
      Serial.println("ERR:COLOR_FORMAT");
      return;
    }
    setAll(r, g, b);
    Serial.println("OK:COLOR");
  } else if (isIntegerCommand(command)) {
    int angle = command.toInt();
    smoothServoMove(headServo1, headAngle1, angle);
    Serial.println("OK:SERVO_1_LEGACY");
  } else {
    Serial.println("ERR:UNKNOWN_HEAD_COMMAND");
  }
}

void setup() {
  Serial.begin(BAUD_RATE);
  delay(1000);

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);

  headServo1.setPeriodHertz(50);
  headServo2.setPeriodHertz(50);
  headServo1.attach(HEAD_SERVO_1_PIN, 500, 2500);
  headServo2.attach(HEAD_SERVO_2_PIN, 500, 2500);
  headServo1.write(headAngle1);
  headServo2.write(headAngle2);

  strip.begin();
  strip.setBrightness(brightnessValue);
  ledOff();

  printReady();
}

void loop() {
  if (!Serial.available()) return;
  String command = Serial.readStringUntil('\n');
  handleCommand(command);
}
