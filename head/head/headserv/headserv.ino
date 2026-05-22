#include <ESP32Servo.h>

#define SERVO_PIN 17

Servo servo360;

void setup() {
  Serial.begin(115200);

  ESP32PWM::allocateTimer(0);
  servo360.setPeriodHertz(50);
  servo360.attach(SERVO_PIN, 500, 2500);

  servo360.write(90); // stop

  Serial.println("360 SERVO TEST READY");
  Serial.println("Send:");
  Serial.println("90 = stop");
  Serial.println("0 = full speed one direction");
  Serial.println("180 = full speed opposite direction");
  Serial.println("80 / 100 = slow movement");
}

void loop() {
  if (Serial.available()) {
    int value = Serial.parseInt();

    if (value >= 0 && value <= 180) {
      servo360.write(value);

      Serial.print("Servo value = ");
      Serial.println(value);
    }

    while (Serial.available()) {
      Serial.read();
    }
  }
}