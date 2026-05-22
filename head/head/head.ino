#include <ESP32Servo.h>

#define SERVO_PIN 17

Servo myServo;

void setup() {
  Serial.begin(115200);

  ESP32PWM::allocateTimer(0);
  myServo.setPeriodHertz(50);

  // Try 500-2500 first
  myServo.attach(SERVO_PIN, 500, 2500);

  Serial.println("Servo test ready");
  Serial.println("Send angle: 0 to 180");
}

void loop() {
  if (Serial.available()) {
    int angle = Serial.parseInt();

    if (angle >= 0 && angle <= 180) {
      myServo.write(angle);

      Serial.print("Servo angle = ");
      Serial.println(angle);
    }

    while (Serial.available()) {
      Serial.read();
    }
  }
}