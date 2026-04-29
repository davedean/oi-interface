# M5StickS3 Hardware Reference

Source: <https://docs.m5stack.com/en/core/StickS3>

## SoC
- ESP32-S3-PICO-1-N8R8 (dual-core Xtensa LX7, up to 240MHz)
- 8MB flash, 8MB octal PSRAM
- 2.4 GHz WiFi, BT5 LE
- USB-C, USB-OTG

## Display
- **ST7789P3** (variant of ST7789 — community st7789 MicroPython drivers should drive it)
- 135 × 240 px

| Function | GPIO |
| --- | --- |
| MOSI | G39 |
| SCK  | G40 |
| RS / DC | G45 |
| CS   | G41 |
| RST  | G21 |
| BL (backlight) | G38 |

## Buttons
| Button | GPIO | Notes |
| --- | --- | --- |
| BtnA (KEY1, front large) | G11 | Active low (assume) |
| BtnB (KEY2, side small)  | G12 | Active low (assume) |

The side power/reset button is separate — it talks to the M5PM1 PMIC, not directly to a GPIO. **Long-press = enter download mode** (green LED flashes). Double-press = power off. Single-press = power on.

## I²C bus
- SDA = G47, SCL = G48
- Devices:
  - 0x18 — ES8311 audio codec
  - 0x68 — BMI270 IMU
  - 0x6e — M5PM1 power management chip (controls EXT_5V_EN, charge state, IRQ, L3B, speaker pulse, IMU INT)

## Audio (ES8311)
- MCLK=G18, BCLK=G17, LRCK=G15, DOUT=G14, DIN=G16
- (Earlier versions of this doc had BCLK and DOUT swapped — corrected 2026-04-25 after cross-checking with M5Stack official docs + M5Unified source. Real values verified twice.)
- I²C control on shared bus (G48/G47)
- Onboard MEMS mic + AW8737 power amp + 8Ω@1W speaker

## IR
- TX = G46, RX = G42 (RX must use ESP32 RMT peripheral, not bitbang)
- Speaker amplifier must be off when receiving IR

## Power
- 250 mAh LiPo battery
- Charged via USB-C
- M5PM1 manages charging, low-power states (L1/L2/L3A/L3B)
- For our use case: USB-powered always; battery is just a backup if unplugged momentarily

## Hat2-Bus (top connector, 16-pin)
| Pin | Signal | Pin | Signal |
| --- | --- | --- | --- |
| 1 | GND | 2 | G5 |
| 3 | EXT_5V | 4 | G4 |
| 5 | Boot | 6 | G6 |
| 7 | G1 | 8 | G7 |
| 9 | G8 | 10 | G43 |
| 11 | BAT | 12 | G44 |
| 13 | 3V3_L2 | 14 | G2 |
| 15 | 5V_IN | 16 | G3 |

## Grove Port (HY2.0-4P, side)
- GND, 5V, G9, G10
- Default: 5V is INPUT mode. To output 5V, must call `M5.Power.setExtOutput(true)` (or equivalent over M5PM1 I²C).

## Bootloader entry (clean version)
1. **Long-press the side button** (~2 seconds) until internal green LED flashes — device is in ROM download mode.
2. Run esptool with `--before no-reset --after no-reset` from the host.
3. After flash, double-press to power off, single-press to power on.

(No more "long-press to off, short-press to wake, race the bootloader window" — that was us being pessimistic.)

## Footprint
- 48 × 24 × 15 mm, 20 g
- Magnetic back
