#include <Arduino.h>
#include <ESP32Servo.h>
#include <Adafruit_NeoPixel.h>

#define BAUD_RATE 115200

#define LED_PIN 4
#define LED_COUNT 84
#define LED_BRIGHTNESS 60

#define HEAD_SERVO_PIN 33

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
Servo headServo;

uint8_t brightnessValue = LED_BRIGHTNESS;

// Continuous servo values
int SERVO_STOP = 1500;
int SERVO_LEFT = 1300;
int SERVO_RIGHT = 1700;

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

void servoStop() {
  headServo.writeMicroseconds(SERVO_STOP);
}

void servoLeft() {
  headServo.writeMicroseconds(SERVO_LEFT);
}

void servoRight() {
  headServo.writeMicroseconds(SERVO_RIGHT);
}

void servoRaw(int us) {
  us = constrain(us, 1000, 2000);
  headServo.writeMicroseconds(us);
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

void printReady() {
  Serial.println("DEVICE:HEAD");
  Serial.println("HEAD READY");
  Serial.println("Commands:");
  Serial.println("PING");
  Serial.println("HEAD LEFT");
  Serial.println("HEAD RIGHT");
  Serial.println("HEAD STOP");
  Serial.println("HEAD SERVO 1500");
  Serial.println("HEAD LED 255 0 0");
  Serial.println("HEAD LED_OFF");
  Serial.println("HEAD RAINBOW");
}

void handleCommand(String command) {
  command.trim();
  if (command.length() == 0) return;

  String upper = command;
  upper.toUpperCase();

  String lower = command;
  lower.toLowerCase();

  if (upper == "PING") {
    Serial.println("DEVICE:HEAD");
    return;
  }

  if (upper == "HEAD LEFT") {
    servoLeft();
    Serial.println("OK:HEAD_LEFT");
    return;
  }

  if (upper == "HEAD RIGHT") {
    servoRight();
    Serial.println("OK:HEAD_RIGHT");
    return;
  }

  if (upper == "HEAD STOP") {
    servoStop();
    Serial.println("OK:HEAD_STOP");
    return;
  }

  if (upper.startsWith("HEAD SERVO ")) {
    int us = command.substring(11).toInt();
    servoRaw(us);
    Serial.print("OK:HEAD_SERVO ");
    Serial.println(us);
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
  } else if (lower.startsWith("brightness")) {
    int value = constrain(command.substring(10).toInt(), 0, 255);
    brightnessValue = value;
    strip.setBrightness(brightnessValue);
    strip.show();

    Serial.print("OK:BRIGHTNESS ");
    Serial.println(brightnessValue);
  } else {
    Serial.println("ERR:UNKNOWN_HEAD_COMMAND");
  }
}

void setup() {
  Serial.begin(BAUD_RATE);
  delay(1000);

  ESP32PWM::allocateTimer(0);

  headServo.setPeriodHertz(50);
  headServo.attach(HEAD_SERVO_PIN, 1000, 2000);

  servoStop();

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