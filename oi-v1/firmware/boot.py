# oi — boot.py
# Runs once at every power-on / soft-reset.
#
# Responsibilities:
#   1. Power on the LCD via the M5PM1 PMIC (GPIO IO2 = L3B_EN rail).
#   2. Init SPI + ST7789 display; fill black.
#   3. Init BtnA (G11) and BtnB (G12) as inputs with pull-ups.
#   4. Connect to WiFi, showing progress on screen.
#
# Exports module-level globals for main.py to import:
#   tft    — ST7789 display object
#   btnA   — Pin(11), active-low, pull-up
#   btnB   — Pin(12), active-low, pull-up
#   wlan   — network.WLAN object (may not be connected if WiFi failed)
#   pmic   — M5PM1 PMIC object (battery_voltage_mV, battery_percent, usb_connected)

import time
import network
from machine import Pin, PWM, SPI, I2C
import m5pm1
import st7789py as st7789
import vga2_8x16 as font_sm

import secrets


# ---------------------------------------------------------------------------
# Backlight wrapper — exposes BOTH .value() (for the st7789py driver, which
# calls backlight.value(1) during init) AND .duty_u16() (for brightness
# control). Both methods drive the same underlying PWM.
# ---------------------------------------------------------------------------

class _BacklightPWM:
    def __init__(self, pin_no, freq=1000, duty_u16=49152):
        self._last_duty = duty_u16
        self._pwm = PWM(Pin(pin_no, Pin.OUT), freq=freq, duty_u16=duty_u16)

    def value(self, v):
        # Driver calls .value(1) during init and .value(0) for sleep.
        if v:
            self._pwm.duty_u16(self._last_duty)
        else:
            self._pwm.duty_u16(0)

    def duty_u16(self, d):
        # Brightness control. Remember the value so .value(1) restores it.
        if d > 0:
            self._last_duty = d
        self._pwm.duty_u16(d)

# ---------------------------------------------------------------------------
# Hardware constants — pin numbers from HARDWARE.md
# ---------------------------------------------------------------------------
_I2C_SDA   = 47
_I2C_SCL   = 48
_I2C_FREQ  = 100_000

_SPI_ID    = 1
_SPI_SCK   = 40
_SPI_MOSI  = 39
_LCD_DC    = 45
_LCD_CS    = 41
_LCD_RST   = 21
_LCD_BL    = 38
_LCD_W     = 135
_LCD_H     = 240

_BTN_A_PIN = 11   # front large button, active-low
_BTN_B_PIN = 12   # side small button, active-low

_WIFI_TIMEOUT_S = 20
_WIFI_POLL_MS   = 250

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status(tft, line, msg, y, fg=st7789.WHITE, bg=st7789.BLACK):
    """Draw a status line at vertical position y, left-aligned."""
    # Pad/truncate to 16 chars so it overwrites any previous text cleanly.
    padded = (msg + " " * 24)[:24]
    tft.text(font_sm, padded, 0, y, fg, bg)


# ---------------------------------------------------------------------------
# Boot sequence — wrapped in try/except so a crash draws on screen
# ---------------------------------------------------------------------------

tft   = None
btnA  = None
btnB  = None
wlan  = None
pmic  = None
audio = None
mic   = None

try:
    # ------------------------------------------------------------------
    # 1. PMIC — enable LCD power rail (IO2 = L3B_EN)
    # ------------------------------------------------------------------
    i2c = I2C(0, sda=Pin(_I2C_SDA), scl=Pin(_I2C_SCL), freq=_I2C_FREQ)
    pmic = m5pm1.M5PM1(i2c)  # exported at module scope for main.py
    pmic.enable_lcd_power()
    time.sleep_ms(50)   # let the rail settle

    # ------------------------------------------------------------------
    # 2. Display init
    # ------------------------------------------------------------------
    spi = SPI(
        _SPI_ID,
        baudrate=40_000_000,
        sck=Pin(_SPI_SCK),
        mosi=Pin(_SPI_MOSI),
    )
    tft = st7789.ST7789(
        spi, _LCD_W, _LCD_H,
        reset=Pin(_LCD_RST, Pin.OUT),
        cs=Pin(_LCD_CS, Pin.OUT),
        dc=Pin(_LCD_DC, Pin.OUT),
        backlight=_BacklightPWM(_LCD_BL, freq=1000, duty_u16=49152),
        rotation=1,   # landscape: 240×135
    )
    tft.fill(st7789.BLACK)

    # ------------------------------------------------------------------
    # 3. Status: booting
    # ------------------------------------------------------------------
    _status(tft, 0, "oi booting...",  y=0)

    # ------------------------------------------------------------------
    # 4. Buttons
    # ------------------------------------------------------------------
    btnA = Pin(_BTN_A_PIN, Pin.IN, Pin.PULL_UP)
    btnB = Pin(_BTN_B_PIN, Pin.IN, Pin.PULL_UP)
    _status(tft, 1, "buttons: ok",    y=16)

    # ------------------------------------------------------------------
    # 5. WiFi
    # ------------------------------------------------------------------
    _status(tft, 2, "wifi: connecting", y=32)

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), _WIFI_TIMEOUT_S * 1000)
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                break
            time.sleep_ms(_WIFI_POLL_MS)

    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        _status(tft, 3, "wifi: " + ip,  y=48, fg=st7789.GREEN)
        # Fire-and-forget boot ping so server logs show device reboots + version.
        try:
            import urequests as _ur
            try:
                from version import VERSION as _ver
            except Exception:
                _ver = "?"
            _url = getattr(secrets, "OI_SERVER_URL", "http://gateway.local:8842")
            _r = _ur.post(_url + "/oi/up", json={"version": _ver})
            _r.close()
        except Exception as _ue:
            print("[boot] up ping failed:", _ue)
    else:
        _status(tft, 3, "wifi: FAILED",  y=48, fg=st7789.RED)

    # ------------------------------------------------------------------
    # 6. WebREPL (OTA updates) — only if wifi is up
    # ------------------------------------------------------------------
    if wlan.isconnected():
        try:
            import webrepl
            pwd = secrets.WEBREPL_PASSWORD
            f = open("/webrepl_cfg.py", "w")
            f.write("PASS = '" + pwd + "'\n")
            f.close()
            webrepl.start()
            _status(tft, 4, "webrepl: ok", y=64, fg=st7789.GREEN)
        except AttributeError:
            # secrets.WEBREPL_PASSWORD not defined
            _status(tft, 4, "webrepl: skip", y=64, fg=st7789.YELLOW)
        except Exception as _e:
            print("[boot] webrepl error:", _e)
            _status(tft, 4, "webrepl: ERR", y=64, fg=st7789.RED)

    # ------------------------------------------------------------------
    # 7. Audio (ES8311 DAC + AW8737 amp) — non-fatal if unavailable
    # ------------------------------------------------------------------
    try:
        from oi_audio import OiAudio
        audio = OiAudio(i2c, pmic=pmic)
        _status(tft, 5, "audio: ok", y=80, fg=st7789.GREEN)
    except Exception as _ae:
        print("[boot] audio init error (non-fatal):", _ae)
        _status(tft, 5, "audio: skip", y=80, fg=st7789.YELLOW)

    # ------------------------------------------------------------------
    # 8. Mic (ES8311 ADC + I2S RX) — non-fatal if unavailable
    # ------------------------------------------------------------------
    try:
        from oi_mic import OiMic
        mic = OiMic(i2c)
        _status(tft, 6, "mic: ok", y=96, fg=st7789.GREEN)
    except Exception as _me:
        print("[boot] mic init error (non-fatal):", _me)
        _status(tft, 6, "mic: skip", y=96, fg=st7789.YELLOW)

    print("[boot] done. wlan connected:", wlan.isconnected())

except Exception as e:
    # Draw the error on screen so we can diagnose without a serial cable.
    msg = str(e)
    print("[boot] ERROR:", msg)
    if tft is not None:
        tft.fill(st7789.BLACK)
        tft.text(font_sm, "BOOT ERROR:",        0,  0, st7789.RED,   st7789.BLACK)
        tft.text(font_sm, (msg + " " * 24)[:24], 0, 16, st7789.WHITE, st7789.BLACK)
        tft.text(font_sm, (msg[24:] + " " * 24)[:24], 0, 32, st7789.WHITE, st7789.BLACK)
