# -*- coding: utf-8 -*-
from modules.perception.pca9685_driver import PCA9685Driver
from modules.perception.hall_encoder import HallEncoderTracker

class LaserSystemController:
    def __init__(self, pca: PCA9685Driver, encoder: HallEncoderTracker,
                 laser_ch: int = 2, n20_in1: int = 0, n20_in2: int = 1):
        self.pca = pca
        self.encoder = encoder
        self.laser_ch = laser_ch
        self.n20_in1 = n20_in1
        self.n20_in2 = n20_in2

        self.laser_enabled = False
        self.laser_power_pct = 60.0
        self.motor_speed_pct = 40.0
        self.motor_direction = "STOP"

    def set_laser_state(self, enabled: bool, power_pct: float = None) -> bool:
        self.laser_enabled = bool(enabled)
        if power_pct is not None:
            self.laser_power_pct = max(0.0, min(100.0, float(power_pct)))

        if self.laser_enabled and self.laser_power_pct > 0.0:
            duty = float(self.laser_power_pct) / 100.0
        else:
            duty = 0.0

        return self.pca.set_duty(self.laser_ch, duty)

    def set_laser_pwm(self, power_pct: float) -> bool:
        self.laser_power_pct = max(0.0, min(100.0, float(power_pct)))
        if self.laser_enabled:
            duty = float(self.laser_power_pct) / 100.0
            return self.pca.set_duty(self.laser_ch, duty)
        return True

    def set_motor(self, direction: str, speed_pct: float = None) -> bool:
        if speed_pct is not None:
            self.motor_speed_pct = max(0.0, min(100.0, float(speed_pct)))
        self.motor_direction = direction.upper()
        duty = float(self.motor_speed_pct) / 100.0

        if self.motor_direction == "FORWARD":
            ok1 = self.pca.set_duty(self.n20_in1, duty)
            ok2 = self.pca.set_duty(self.n20_in2, 0.0)
            return ok1 and ok2
        elif self.motor_direction == "BACKWARD":
            ok1 = self.pca.set_duty(self.n20_in1, 0.0)
            ok2 = self.pca.set_duty(self.n20_in2, duty)
            return ok1 and ok2
        else:
            self.motor_direction = "STOP"
            ok1 = self.pca.set_duty(self.n20_in1, 0.0)
            ok2 = self.pca.set_duty(self.n20_in2, 0.0)
            return ok1 and ok2