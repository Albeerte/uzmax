// ================================================================
//  UzMAX Robot — ESP32_HAND  (exact user firmware, unchanged)
//  Protocol:  R 1 90  /  L 6 120
//  This IS the firmware — do NOT use the old HAND R 1 90 syntax.
// ================================================================

#include <ESP32Servo.h>
#define BAUD_RATE 115200

struct HandServo {
  Servo servo;
  char hand;        // R or L
  int number;       // 1-6
  int pin;
  int startAngle;
  int minAngle;
  int maxAngle;
  int currentAngle;
};

HandServo servos[] = {
  // RIGHT
  // servo, hand, number, pin, start, min, max, current
  { Servo(), 'R',    1,    13,  90,   0,     180,  90 },
  { Servo(), 'R',    2,    12,  175,   0,    180,  175 },
  { Servo(), 'R',    3,    14,  90,  0,    180,  90 },
  { Servo(), 'R',    4,    27,   0,   0,    180,   0 },
  { Servo(), 'R',    5,    26,  0,  0,    180,  0 },
  { Servo(), 'R',    6,    25,   90,   0,     180,   90 },
  // LEFT
  // servo, hand, number, pin, start, min, max, current
  { Servo(), 'L',   1,     33,  100,   0,    180,   100 },
  { Servo(), 'L',   2,     32,   10,   0,   180,    0 },
  { Servo(), 'L',   3,     23,  90,   0,    180,   90 },
  { Servo(), 'L',   4,     22, 0,   0,   180,  0 },
  { Servo(), 'L',   5,     21,  90,  0,   180,   90 },
  { Servo(), 'L',   6,     19,  90,   0,    180,   90 }
};

const int SERVO_COUNT = sizeof(servos) / sizeof(servos[0]);
int smoothDelay = 8;  // smaller = faster, bigger = slower

int clampAngle(int value, int minValue, int maxValue) {
  if (value < minValue) return minValue;
  if (value > maxValue) return maxValue;
  return value;
}

int findServo(char hand, int number) {
  hand = toupper(hand);
  for (int i = 0; i < SERVO_COUNT; i++) {
    if (servos[i].hand == hand && servos[i].number == number) {
      return i;
    }
  }
  return -1;
}

void moveServoSmooth(int index, int targetAngle) {
  targetAngle = clampAngle(
    targetAngle,
    servos[index].minAngle,
    servos[index].maxAngle
  );
  int current = servos[index].currentAngle;
  if (current == targetAngle) {
    Serial.print("OK ");
    Serial.print(servos[index].hand);
    Serial.print(servos[index].number);
    Serial.print(" already at ");
    Serial.println(targetAngle);
    return;
  }
  int step = targetAngle > current ? 1 : -1;
  while (current != targetAngle) {
    current += step;
    servos[index].servo.write(current);
    servos[index].currentAngle = current;
    delay(smoothDelay);
  }
  Serial.print("OK ");
  Serial.print(servos[index].hand);
  Serial.print(servos[index].number);
  Serial.print(" = ");
  Serial.println(targetAngle);
}

void handleCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();
  if (cmd.length() == 0) return;

  // PING — used by server to identify device (optional extension)
  if (cmd == "PING") {
    Serial.println("DEVICE:HAND");
    return;
  }

  int firstSpace = cmd.indexOf(' ');
  int secondSpace = cmd.indexOf(' ', firstSpace + 1);

  if (firstSpace == -1 || secondSpace == -1) {
    Serial.println("ERROR format must be: r 1 90");
    return;
  }

  char hand = cmd.charAt(0);
  int servoNumber = cmd.substring(firstSpace + 1, secondSpace).toInt();
  int angle = cmd.substring(secondSpace + 1).toInt();

  if (hand != 'R' && hand != 'L') {
    Serial.println("ERROR hand must be r or l");
    return;
  }
  if (servoNumber < 1 || servoNumber > 6) {
    Serial.println("ERROR servo number must be 1 to 6");
    return;
  }

  int index = findServo(hand, servoNumber);
  if (index == -1) {
    Serial.println("ERROR servo not found");
    return;
  }

  moveServoSmooth(index, angle);
}

void setup() {
  Serial.begin(BAUD_RATE);
  delay(1000);

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

  for (int i = 0; i < SERVO_COUNT; i++) {
    servos[i].servo.setPeriodHertz(50);
    // If servo shakes, change to 600, 2400.
    servos[i].servo.attach(servos[i].pin, 600, 2400);
    servos[i].servo.write(servos[i].startAngle);
    servos[i].currentAngle = servos[i].startAngle;
    delay(100);
  }

  Serial.println("DEVICE:HAND");
  Serial.println("ESP32 12 SERVO CONTROL READY");
  Serial.println("Use: r 1 90");
  Serial.println("Use: l 6 0");
}

void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    handleCommand(command);
  }
}
