# Minimal M5PM1 driver — LCD power rail + battery monitoring.
# Datasheet: m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1207/M5PM1_Datasheet_EN.pdf
#
# M5PM1 is the M5StickS3's on-board power-management chip. It sits on the
# internal I2C bus at 0x6E. Several of M5PM1's own GPIOs control board-level
# power rails, including:
#   IO2 → L3B_EN (LCD VDD rail). Must be HIGH or the LCD has no power.
#
# Register sources (confirmed from two independent sources):
#   1. github.com/m5stack/M5PM1/blob/master/src/M5PM1.h  (official M5Stack driver)
#   2. github.com/m5stack/M5Unified/blob/master/src/utility/Power_Class.cpp
#      — getBatteryVoltage() reads 0x22/0x23, little-endian, result in mV
#      — isCharging() reads 0x12 bit 0: 0=charging, 1=discharging (M5StickS3)
#   VIN (0x24/0x25) presence used as USB-connected proxy (> 1000 mV = USB present).

ADDR = 0x6E

# Registers we care about
R_DEVICE_ID  = 0x00  # should read 0x50
R_GPIO_MODE  = 0x10  # bits[4:0] = output(1)/input(0) for GPIO4..0
R_GPIO_OUT   = 0x11  # bits[4:0] = high(1)/low(0)
R_GPIO_IN    = 0x12  # read-only, real-time input; bit0 = charge status (0=charging)
R_GPIO_DRV   = 0x13  # bits[4:0] = open-drain(1)/push-pull(0)
R_GPIO_FUNC0 = 0x16  # bits[7:6]=GPIO3 [5:4]=GPIO2 [3:2]=GPIO1 [1:0]=GPIO0; 0b00 = plain GPIO
R_GPIO_FUNC1 = 0x17  # bits[1:0]=GPIO4

# ADC / voltage registers (little-endian 12-bit, unit = millivolts)
R_VBAT_L = 0x22  # battery voltage low byte
R_VBAT_H = 0x23  # battery voltage high nibble
R_VIN_L  = 0x24  # VIN / VBUS voltage low byte
R_VIN_H  = 0x25  # VIN / VBUS voltage high nibble

# LiPo charge curve approximation (mV)
_BAT_MIN_MV = 3300
_BAT_MAX_MV = 4200

# Board-level PMIC GPIO assignments.
_LCD_POWER_GPIO = 2  # IO2 -> L3B_EN (LCD VDD rail)
_SPEAKER_AMP_GPIO = 3  # IO3 -> AW8737 speaker amplifier enable

GPIO_MODE_OUTPUT = 1
GPIO_MODE_INPUT  = 0
DRV_PUSH_PULL    = 0
DRV_OPEN_DRAIN   = 1


class M5PM1:
    def __init__(self, i2c, addr=ADDR):
        self.i2c = i2c
        self.addr = addr

    def _r(self, reg):
        return self.i2c.readfrom_mem(self.addr, reg, 1)[0]

    def _w(self, reg, val):
        self.i2c.writeto_mem(self.addr, reg, bytes([val & 0xFF]))

    def _set_bit(self, reg, bit, on):
        v = self._r(reg)
        if on:
            v |= (1 << bit)
        else:
            v &= ~(1 << bit)
        self._w(reg, v)

    def device_id(self):
        return self._r(R_DEVICE_ID)

    def gpio_set_function_plain(self, pin):
        # Force the FUNC bits for this pin to 00 (plain GPIO).
        if pin < 4:
            v = self._r(R_GPIO_FUNC0)
            v &= ~(0b11 << (pin * 2))
            self._w(R_GPIO_FUNC0, v)
        else:  # pin == 4
            v = self._r(R_GPIO_FUNC1)
            v &= ~0b11
            self._w(R_GPIO_FUNC1, v)

    def gpio_set_drive(self, pin, drv):
        # 0 = push-pull, 1 = open-drain
        self._set_bit(R_GPIO_DRV, pin, drv)

    def gpio_set_mode(self, pin, mode):
        # 0 = input, 1 = output
        self._set_bit(R_GPIO_MODE, pin, mode)

    def gpio_write(self, pin, val):
        self._set_bit(R_GPIO_OUT, pin, 1 if val else 0)

    def gpio_read(self, pin):
        return (self._r(R_GPIO_IN) >> pin) & 1

    def _configure_output_gpio(self, pin, on):
        """Configure a PMIC GPIO as plain push-pull output and drive it."""
        self.gpio_set_function_plain(pin)
        self.gpio_set_drive(pin, DRV_PUSH_PULL)
        self.gpio_set_mode(pin, GPIO_MODE_OUTPUT)
        self.gpio_write(pin, 1 if on else 0)

    # Higher-level: enable LCD power rail.
    def enable_lcd_power(self):
        # IO2 = L3B_EN. Function=plain GPIO, push-pull output, drive HIGH.
        self._configure_output_gpio(_LCD_POWER_GPIO, True)

    def enable_speaker_amp(self, on=True):
        """Enable/disable the AW8737 speaker amplifier via PMIC IO3."""
        self._configure_output_gpio(_SPEAKER_AMP_GPIO, on)

    def _read_mv(self, reg_l):
        """Read a 12-bit little-endian millivolt value from reg_l and reg_l+1."""
        buf = self.i2c.readfrom_mem(self.addr, reg_l, 2)
        return ((buf[1] & 0x0F) << 8) | buf[0]

    def battery_voltage_mV(self):
        """Read battery voltage in millivolts (12-bit, little-endian from 0x22/0x23).

        Sources: M5PM1.h (M5PM1_REG_VBAT_L=0x22, M5PM1_REG_VBAT_H=0x23)
                 M5Unified Power_Class.cpp getBatteryVoltage() case pmic_m5pm1
        Returns int mV, e.g. 3700 for a half-charged LiPo.
        """
        return self._read_mv(R_VBAT_L)

    def battery_percent(self):
        """Return battery charge estimate as 0-100.

        Linear approximation over LiPo range 3300 mV (empty) → 4200 mV (full).
        """
        mV = self.battery_voltage_mV()
        return max(0, min(100, (mV - _BAT_MIN_MV) * 100 // (_BAT_MAX_MV - _BAT_MIN_MV)))

    def usb_connected(self):
        """True if USB/VBUS power is present (VIN > 1000 mV).

        Reads VIN register pair 0x24/0x25. A reading above 1000 mV indicates
        USB power is available (typical USB = ~4900-5100 mV).
        Source: M5PM1.h (M5PM1_REG_VIN_L=0x24), M5Unified getVBUSVoltage().
        """
        return self._read_mv(R_VIN_L) > 1000
