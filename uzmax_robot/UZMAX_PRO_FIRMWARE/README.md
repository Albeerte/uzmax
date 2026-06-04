# UzMAX Professional Firmware

Clean firmware pack used by the local dashboard Upload page.

- `ESP32_HEAD`: head servos plus 84 LED NeoPixel effects.
- `ESP32_HAND`: 12 hand servos with `R 1 90` / `L 6 120`.
- `ESP32_MOVE`: dual TMC stepper controller with advanced commands and dashboard `MOVE ...` commands.

All devices respond to `PING` with `DEVICE:HEAD`, `DEVICE:HAND`, or `DEVICE:MOVE`.

