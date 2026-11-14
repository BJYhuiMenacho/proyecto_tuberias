# -*- coding: utf-8 -*-
import time
import threading
from typing import Dict, Any

from utils.i2c_manager import ThreadSafeI2CManager
from modules.telemetry.ina219_driver import INA219Driver
from modules.perception.pca9685_driver import PCA9685Driver
from modules.perception.hall_encoder import HallEncoderTracker
from modules.perception.laser_controller import LaserSystemController
from modules.comms.uart_bridge import UARTLocomotionBridge

class CoreOrchestrator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.chassis_mode_auto = False

        # 1. Bus I2C-4 y Sensores (PCA9685 @ 0x40, INA219 @ 0x44)
        i2c_cfg = config.get("i2c", {})
        bus_id = i2c_cfg.get("bus_id", 4)
        pca_addr = i2c_cfg.get("pca9685_address", 0x40)
        ina_addr = i2c_cfg.get("ina219_address", 0x44)

        self.i2c_mgr = ThreadSafeI2CManager(bus_id=bus_id)
        self.pca = PCA9685Driver(bus_id=bus_id, address=pca_addr)
        self.ina = INA219Driver(bus_id=bus_id, address=ina_addr)

        # 2. Encoder Hall (gpiochip3, offset 20 y 1)
        enc_cfg = config.get("gpio_encoder", {})
        self.encoder = HallEncoderTracker(
            chip_num=enc_cfg.get("chip_num", 3),
            pin_a=enc_cfg.get("pin_out_a", 20),
            pin_b=enc_cfg.get("pin_out_b", 1),
            gear_ratio=enc_cfg.get("gear_ratio", 298.0),
            cpr_motor=enc_cfg.get("cpr_motor", 3.0)
        )

        # 3. Controlador de Láser (Canal 2) y Motor N20 (Canales 0 y 1)
        act_cfg = config.get("actuators", {})
        n20_cfg = act_cfg.get("laser_rotator_n20", {})
        self.laser_ctl = LaserSystemController(
            pca=self.pca,
            encoder=self.encoder,
            laser_ch=act_cfg.get("laser_pwm_channel", 2),
            n20_in1=n20_cfg.get("ch_in1", 0),
            n20_in2=n20_cfg.get("ch_in2", 1)
        )

        # 4. Puente UART con Arduino Nano (/dev/ttyS3)
        uart_cfg = config.get("uart_locomotion", {})
        self.uart = UARTLocomotionBridge(
            port=uart_cfg.get("port", "/dev/ttyS3"),
            baudrate=uart_cfg.get("baudrate", 115200),
            timeout_s=uart_cfg.get("timeout_s", 0.05)
        )

        # 5. Acumulador de energía
        self.energy_joules = 0.0
        self.last_energy_ts = time.time()
        self.latest_elec = self.ina.read_metrics()
        self.cpu_temp_c = 0.0

        self.running = True
        self.bg_thread = threading.Thread(target=self._background_sampler, daemon=True)
        self.bg_thread.start()

    def _read_cpu_temp(self) -> float:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return round(float(f.read().strip()) / 1000.0, 1)
        except Exception:
            return 0.0

    def _background_sampler(self) -> None:
        while self.running:
            now = time.time()
            dt = now - self.last_energy_ts
            self.last_energy_ts = now

            self.latest_elec = self.ina.read_metrics()
            self.cpu_temp_c = self._read_cpu_temp()

            if dt > 0 and self.latest_elec.power_mw > 0:
                self.energy_joules += (self.latest_elec.power_mw / 1000.0) * dt

            time.sleep(0.5)

    def get_hardware_health(self) -> Dict[str, str]:
        pca_ok = False
        try:
            self.i2c_mgr.read_byte_data(self.pca.address, 0x00)
            pca_ok = True
            self.pca.is_available = True
        except Exception:
            self.pca.is_available = False

        ina_ok = self.ina.is_available
        i2c_ok = pca_ok or ina_ok
        uart_ok = self.uart.is_port_open()
        enc_ok = self.encoder.is_available

        return {
            "bus_i2c": "OK" if i2c_ok else "FAILED",
            "sensor_ina219": "OK" if ina_ok else "FAILED",
            "pwm_pca9685": "OK" if pca_ok else "FAILED",
            "uart_locomotion": "OK" if uart_ok else "FAILED",
            "encoder_hall": "OK" if enc_ok else "FAILED"
        }

    def get_full_state(self) -> Dict[str, Any]:
        chassis = self.uart.get_telemetry()
        health = self.get_hardware_health()

        return {
            "voltage_v": self.latest_elec.bus_voltage_v,
            "current_ma": self.latest_elec.current_ma,
            "power_mw": self.latest_elec.power_mw,
            "energy_j": round(self.energy_joules, 1),
            "cpu_temp_c": self.cpu_temp_c,

            "pitch_deg": chassis["pitch_deg"],
            "roll_deg": chassis["roll_deg"],
            "cell_pressure_v": chassis["cell_pressure_v"],
            "chassis_dir": chassis["chassis_dir"],
            "chassis_speed": chassis["chassis_speed"],
            "arduino_streaming": chassis["arduino_streaming"],
            "mode_auto": self.chassis_mode_auto,

            "laser_enabled": self.laser_ctl.laser_enabled,
            "laser_power_pct": self.laser_ctl.laser_power_pct,
            "laser_motor_speed": self.laser_ctl.motor_speed_pct,
            "laser_motor_dir": self.laser_ctl.motor_direction,
            "laser_angle_deg": self.encoder.get_angle_deg(),

            "hardware_health": health
        }

    def shutdown(self) -> None:
        self.running = False
        self.laser_ctl.set_laser_state(False, 0.0)
        self.laser_ctl.set_motor("STOP", 0.0)
        self.uart.stop()
        self.uart.stop_piston()
        self.encoder.stop()
        self.uart.close()