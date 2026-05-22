#include <Adafruit_NeoPixel.h>

#define LED_PIN 6        // Arduino data pin
#define LED_COUNT 84
     // Change this to your LED count

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

void setup() {
  strip.begin();
  strip.setBrightness(80);   // 0-255, keep low first
  strip.show();              // Turn off all LEDs
}

void loop() {
  // Red
  setAll(255, 0, 0);
  delay(1000);

  // Green
  setAll(0, 255, 0);
  delay(1000);

  // Blue
  setAll(0, 0, 255);
  delay(1000);

  // White
  setAll(255, 255, 255);
  delay(1000);

  // Rainbow animation
  rainbow(10);
}

void setAll(byte r, byte g, byte b) {
  for (int i = 0; i < LED_COUNT; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
  strip.show();
}

void rainbow(int wait) {
  for (long firstPixelHue = 0; firstPixelHue < 5 * 65536; firstPixelHue += 256) {
    for (int i = 0; i < LED_COUNT; i++) {
      int pixelHue = firstPixelHue + (i * 65536L / LED_COUNT);
      strip.setPixelColor(i, strip.gamma32(strip.ColorHSV(pixelHue)));
    }
    strip.show();
    delay(wait);
  }
}