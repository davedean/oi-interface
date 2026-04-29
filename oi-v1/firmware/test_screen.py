# Test the M5StickS3 LCD via st7789py driver.
# Pins per docs.m5stack.com/en/core/StickS3:
#   MOSI=G39  SCK=G40  DC=G45  CS=G41  RST=G21  BL=G38

from machine import Pin, SPI
import st7789py
import vga2_bold_16x32 as bigfont
import vga2_8x16 as smallfont

# SPI bus — ESP32-S3 SPI(1) supports any pins via GPIO matrix
spi = SPI(1, baudrate=40_000_000, sck=Pin(40), mosi=Pin(39))

tft = st7789py.ST7789(
    spi,
    135, 240,
    reset=Pin(21, Pin.OUT),
    cs=Pin(41, Pin.OUT),
    dc=Pin(45, Pin.OUT),
    backlight=Pin(38, Pin.OUT),
    rotation=0,
)

tft.fill(st7789py.BLACK)

# "oi" big, centred-ish. bigfont is 16x32; "oi" is 2 chars = 32 wide.
# 135 width → centred at (135-32)//2 = 51. 240 height → centred at (240-32)//2 = 104.
tft.text(bigfont, "oi", 51, 104, st7789py.YELLOW, st7789py.BLACK)

# Status line bottom in small font
tft.text(smallfont, "wifi: gateway.local", 4, 220, st7789py.CYAN, st7789py.BLACK)

print("screen test done")
