# -*- coding: utf-8 -*-
import time
import threading
from smbus2 import SMBus

class ThreadSafeI2CManager:
    _instances = {}
    _init_lock = threading.Lock()

    def __new__(cls, bus_id: int = 4, max_retries: int = 3, retry_delay_s: float = 0.005):
        with cls._init_lock:
            if bus_id not in cls._instances:
                instance = super(ThreadSafeI2CManager, cls).__new__(cls)
                instance._initialized = False
                cls._instances[bus_id] = instance
            return cls._instances[bus_id]

    def __init__(self, bus_id: int = 4, max_retries: int = 3, retry_delay_s: float = 0.005):
        if getattr(self, "_initialized", False):
            return
        self.bus_id = bus_id
        self.max_retries = max_retries
        self.retry_delay_s = retry_delay_s
        self.lock = threading.Lock()
        self.bus = None
        self.retry_count = 0
        self._open_bus()
        self._initialized = True

    def _open_bus(self) -> None:
        try:
            self.bus = SMBus(self.bus_id)
        except Exception as e:
            print(f"[I2C-Manager] Error abriendo bus {self.bus_id}: {e}")
            self.bus = None

    def write_byte_data(self, addr: int, reg: int, val: int) -> None:
        with self.lock:
            if self.bus is None:
                self._open_bus()
                if self.bus is None:
                    raise IOError("Bus I2C no disponible")
            for attempt in range(self.max_retries):
                try:
                    self.bus.write_byte_data(addr, reg, val & 0xFF)
                    return
                except Exception as e:
                    self.retry_count += 1
                    time.sleep(self.retry_delay_s)
                    if attempt == self.max_retries - 1:
                        raise e

    def read_byte_data(self, addr: int, reg: int) -> int:
        with self.lock:
            if self.bus is None:
                self._open_bus()
                if self.bus is None:
                    raise IOError("Bus I2C no disponible")
            for attempt in range(self.max_retries):
                try:
                    return self.bus.read_byte_data(addr, reg)
                except Exception as e:
                    self.retry_count += 1
                    time.sleep(self.retry_delay_s)
                    if attempt == self.max_retries - 1:
                        raise e
        return 0

    def write_word_data_be(self, addr: int, reg: int, val: int) -> None:
        swapped = ((val & 0xFF) << 8) | ((val >> 8) & 0xFF)
        with self.lock:
            if self.bus is None:
                self._open_bus()
                if self.bus is None:
                    raise IOError("Bus I2C no disponible")
            for attempt in range(self.max_retries):
                try:
                    self.bus.write_word_data(addr, reg, swapped)
                    return
                except Exception as e:
                    self.retry_count += 1
                    time.sleep(self.retry_delay_s)
                    if attempt == self.max_retries - 1:
                        raise e

    def read_word_data_be(self, addr: int, reg: int) -> int:
        with self.lock:
            if self.bus is None:
                self._open_bus()
                if self.bus is None:
                    raise IOError("Bus I2C no disponible")
            for attempt in range(self.max_retries):
                try:
                    raw = self.bus.read_word_data(addr, reg)
                    return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)
                except Exception as e:
                    self.retry_count += 1
                    time.sleep(self.retry_delay_s)
                    if attempt == self.max_retries - 1:
                        raise e
        return 0