# -*- coding: utf-8 -*-
from dataclasses import dataclass
from utils.i2c_manager import ThreadSafeI2CManager

REG_CONFIG = 0x00
REG_SHUNTVOLTAGE = 0x01
REG_BUSVOLTAGE = 0x02
REG_POWER = 0x03
REG_CURRENT = 0x04
REG_CALIBRATION = 0x05

@dataclass
class ElectricalMetrics:
    bus_voltage_v: float = 0.0
    shunt_voltage_mv: float = 0.0
    current_ma: float = 0.0
    power_mw: float = 0.0

class INA219Driver:
    def __init__(self, bus_id: int = 4, address: int = 0x44):
        self.address = address
        self.i2c = ThreadSafeI2CManager(bus_id=bus_id)
        self._current_lsb = 0.1
        self._power_lsb = 0.002
        self.is_available = False
        self.try_initialize()

    def try_initialize(self) -> bool:
        try:
            cal_value = 4096
            self.i2c.write_word_data_be(self.address, REG_CALIBRATION, cal_value)
            config_val = (0x01 << 13) | (0x03 << 11) | (0x03 << 7) | (0x03 << 3) | 0x07
            self.i2c.write_word_data_be(self.address, REG_CONFIG, config_val)
            self.is_available = True
            return True
        except Exception:
            self.is_available = False
            return False

    def read_metrics(self) -> ElectricalMetrics:
        if not self.is_available:
            if not self.try_initialize():
                return ElectricalMetrics()
        try:
            raw_bus = self.i2c.read_word_data_be(self.address, REG_BUSVOLTAGE)
            bus_v = (raw_bus >> 3) * 0.004

            raw_shunt = self.i2c.read_word_data_be(self.address, REG_SHUNTVOLTAGE)
            if raw_shunt > 32767:
                raw_shunt -= 65536
            shunt_mv = raw_shunt * 0.01

            raw_curr = self.i2c.read_word_data_be(self.address, REG_CURRENT)
            if raw_curr > 32767:
                raw_curr -= 65536
            current_ma = raw_curr * self._current_lsb

            raw_power = self.i2c.read_word_data_be(self.address, REG_POWER)
            power_mw = raw_power * (self._power_lsb * 1000.0)

            return ElectricalMetrics(
                bus_voltage_v=round(bus_v, 2),
                shunt_voltage_mv=round(shunt_mv, 2),
                current_ma=round(current_ma, 1),
                power_mw=round(power_mw, 1)
            )
        except Exception:
            self.is_available = False
            return ElectricalMetrics()