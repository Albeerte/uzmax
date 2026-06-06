#include <Arduino.h>
#include <ESP32Servo.h>
#include <Adafruit_NeoPixel.h>

#define BAUD_RATE 115200

#define LED_PIN 4
#define LED_COUNT 84
#define LED_BRIGHTNESS 60
#define LED_ORDER_DEFAULT "RGB"

#define HEAD_SERVO_PIN 33

// Keep the library in RGB mode and do logical->physical color mapping ourselves.
// If colors are mixed, change from the website with HEAD LED_ORDER RGB/GRB/BRG/etc.
Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_RGB + NEO_KHZ800);
Servo headServo;

uint8_t brightnessValue = LED_BRIGHTNESS;
String ledOrder = LED_ORDER_DEFAULT;

void mapColor(uint8_t r, uint8_t g, uint8_t b, uint8_t &outR, uint8_t &outG, uint8_t &outB) {
  if (ledOrder == "RGB") {
    outR = r; outG = g; outB = b;
  } else if (ledOrder == "RBG") {
    outR = r; outG = b; outB = g;
  } else if (ledOrder == "GRB") {
    outR = g; outG = r; outB = b;
  } else if (ledOrder == "GBR") {
    outR = g; outG = b; outB = r;
  } else if (ledOrder == "BRG") {
    outR = b; outG = r; outB = g;
  } else if (ledOrder == "BGR") {
    outR = b; outG = g; outB = r;
  } else {
    outR = r; outG = g; outB = b;
  }
}

void setAll(uint8_t r, uint8_t g, uint8_t b) {
  uint8_t outR, outG, outB;
  mapColor(r, g, b, outR, outG, outB);
  for (int i = 0; i < LED_COUNT; i++) {
    strip.setPixelColor(i, strip.Color(outR, outG, outB));
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

void rainbow(int waitMs) {
  for (long hue = 0; hue < 65536; hue += 256) {
    if (Serial.available()) return;

    for (int i = 0; i < LED_COUNT; i++) {
      int pixelHue = hue + (i * 65536L / LED_COUNT);
      uint32_t rgb = strip.gamma32(strip.ColorHSV(pixelHue));
      uint8_t r = (uint8_t)(rgb >> 16);
      uint8_t g = (uint8_t)(rgb >> 8);
      uint8_t b = (uint8_t)rgb;
      uint8_t outR, outG, outB;
      mapColor(r, g, b, outR, outG, outB);
      strip.setPixelColor(i, strip.Color(outR, outG, outB));
    }

    strip.show();
    delay(waitMs);
  }
}

void servoStop() {
  headServo.write(90);
}

void servoLeft(int speedValue) {
  speedValue = constrain(speedValue, 0, 90);
  headServo.write(90 - speedValue);
}

void servoRight(int speedValue) {
  speedValue = constrain(speedValue, 0, 90);
  headServo.write(90 + speedValue);
}

void printReady() {
  Serial.println("DEVICE:HEAD");
  Serial.println("HEAD READY");
  Serial.println("Commands:");
  Serial.println("PING");
  Serial.println("HEAD LEFT 40");
  Serial.println("HEAD RIGHT 40");
  Serial.println("HEAD STOP");
  Serial.println("HEAD LED 255 0 0");
  Serial.println("HEAD BRIGHTNESS 60");
  Serial.println("HEAD LED_ORDER RGB");
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

  if (upper.startsWith("HEAD LEFT")) {
    int speedValue = command.substring(9).toInt();
    if (speedValue <= 0) speedValue = 40;

    servoLeft(speedValue);
    Serial.println("OK:HEAD_LEFT");
    return;
  }

  if (upper.startsWith("HEAD RIGHT")) {
    int speedValue = command.substring(10).toInt();
    if (speedValue <= 0) speedValue = 40;

    servoRight(speedValue);
    Serial.println("OK:HEAD_RIGHT");
    return;
  }

  if (upper == "HEAD STOP") {
    servoStop();
    Serial.println("OK:HEAD_STOP");
    return;
  }

  if (upper.startsWith("HEAD SERVO ")) {
    int value = constrain(command.substring(11).toInt(), 0, 180);
    headServo.write(value);
    Serial.println("OK:HEAD_SERVO_RAW");
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

  if (upper.startsWith("HEAD BRIGHTNESS ")) {
    int value = constrain(command.substring(16).toInt(), 0, 255);
    brightnessValue = value;
    strip.setBrightness(brightnessValue);
    strip.show();

    Serial.print("OK:BRIGHTNESS ");
    Serial.println(brightnessValue);
    return;
  }

  if (upper.startsWith("HEAD LED_ORDER ")) {
    String orderValue = command.substring(15);
    orderValue.trim();
    orderValue.toUpperCase();
    if (orderValue == "RGB" || orderValue == "RBG" || orderValue == "GRB" ||
        orderValue == "GBR" || orderValue == "BRG" || orderValue == "BGR") {
      ledOrder = orderValue;
      Serial.print("OK:LED_ORDER ");
      Serial.println(ledOrder);
    } else {
      Serial.println("ERR:LED_ORDER");
    }
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
  headServo.attach(HEAD_SERVO_PIN, 500, 2500);

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
