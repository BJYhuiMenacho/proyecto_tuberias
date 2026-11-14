# -*- coding: utf-8 -*-
import time
from utils.i2c_manager import ThreadSafeI2CManager

MODE1 = 0x00
MODE2 = 0x01
PRESCALE = 0xFE
LED0_ON_L = 0x06

class PCA9685Driver:
    def __init__(self, bus_id: int = 4, address: int = 0x40, freq_hz: float = 250.0):
        self.address = address
        self.freq_hz = freq_hz
        self.i2c = ThreadSafeI2CManager(bus_id=bus_id)
        self.is_available = False
        self.try_initialize()

    def try_initialize(self) -> bool:
        try:
            self.i2c.write_byte_data(self.address, MODE1, 0x00)
            time.sleep(0.005)
            self.i2c.write_byte_data(self.address, MODE2, 0x04) # Totem-pole
            self.set_pwm_freq(self.freq_hz)
            self.is_available = True
            # Apagar por seguridad al iniciar (canales 0, 1 y 2)
            self.set_duty(0, 0.0)
            self.set_duty(1, 0.0)
            self.set_duty(2, 0.0)
            return True
        except Exception as e:
            print(f"[PCA9685] No disponible en 0x{self.address:02X}: {e}")
            self.is_available = False
            return False

    def set_pwm_freq(self, freq_hz: float) -> None:
        prescale_val = round(25000000.0 / (4096.0 * float(freq_hz))) - 1
        prescale = int(max(3, min(255, prescale_val)))

        old_mode = self.i2c.read_byte_data(self.address, MODE1)
        sleep_mode = (old_mode & 0x7F) | 0x10
        self.i2c.write_byte_data(self.address, MODE1, sleep_mode)
        self.i2c.write_byte_data(self.address, PRESCALE, prescale)
        self.i2c.write_byte_data(self.address, MODE1, old_mode)
        time.sleep(0.005)
        self.i2c.write_byte_data(self.address, MODE1, old_mode | 0xA0)

    def set_duty(self, ch: int, duty: float) -> bool:
        if not self.is_available:
            if not self.try_initialize():
                return False

        duty = max(0.0, min(1.0, float(duty)))
        ch = int(ch) & 0x0F
        reg = LED0_ON_L + 4 * ch

        try:
            if duty <= 0.0:
                self.i2c.write_byte_data(self.address, reg + 0, 0x00)
                self.i2c.write_byte_data(self.address, reg + 1, 0x00)
                self.i2c.write_byte_data(self.address, reg + 2, 0x00)
                self.i2c.write_byte_data(self.address, reg + 3, 0x10)
            elif duty >= 1.0:
                self.i2c.write_byte_data(self.address, reg + 0, 0x00)
                self.i2c.write_byte_data(self.address, reg + 1, 0x10)
                self.i2c.write_byte_data(self.address, reg + 2, 0x00)
                self.i2c.write_byte_data(self.address, reg + 3, 0x00)
            else:
                off_tick = int(duty * 4095)
                self.i2c.write_byte_data(self.address, reg + 0, 0x00)
                self.i2c.write_byte_data(self.address, reg + 1, 0x00)
                self.i2c.write_byte_data(self.address, reg + 2, off_tick & 0xFF)
                self.i2c.write_byte_data(self.address, reg + 3, (off_tick >> 8) & 0x0F)
            return True
        except Exception as e:
            print(f"[PCA9685] Error escribiendo canal {ch}: {e}")
            self.is_available = False
            return False