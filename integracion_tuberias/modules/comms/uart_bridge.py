# -*- coding: utf-8 -*-
import serial
import threading
import time
from typing import Dict, Any

class UARTLocomotionBridge:
    def __init__(self, port: str = "/dev/ttyS3", baudrate: int = 115200, timeout_s: float = 0.1):
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.serial_conn = None
        self.running = True
        self.lock = threading.Lock()

        self.latest_telemetry: Dict[str, Any] = {
            "pitch_deg": 0.0,
            "roll_deg": 0.0,
            "cell_pressure_v": 0.0,
            "chassis_dir": 0,
            "chassis_speed": 150.0,
            "last_rx_time": 0.0
        }

        self._try_open()
        self.worker = threading.Thread(target=self._reader_loop, daemon=True)
        self.worker.start()

    def _try_open(self) -> bool:
        try:
            if self.serial_conn and self.serial_conn.is_open:
                return True
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout_s,
                dsrdtr=False,
                rtscts=False
            )
            self.serial_conn.dtr = False
            self.serial_conn.rts = False
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            print(f"[UART] Puerto {self.port} abierto exitosamente.")
            return True
        except Exception:
            self.serial_conn = None
            return False

    def is_port_open(self) -> bool:
        return bool(self.serial_conn and self.serial_conn.is_open)

    def _reader_loop(self) -> None:
        buffer = ""
        while self.running:
            if not self.is_port_open():
                self._try_open()
                time.sleep(1.0)
                continue
            try:
                waiting = self.serial_conn.in_waiting
                if waiting > 0:
                    raw_bytes = self.serial_conn.read(waiting)
                    buffer += raw_bytes.decode("ascii", errors="ignore")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if (line.startswith("$IMU,") or line.startswith("$TEL,")) and line.endswith("*"):
                            self._parse_telemetry(line)
            except Exception:
                try:
                    self.serial_conn.close()
                except Exception:
                    pass
                self.serial_conn = None
                time.sleep(0.5)
            time.sleep(0.01)

    def _parse_telemetry(self, line: str) -> None:
        try:
            idx_start = line.find(",") + 1
            body = line[idx_start:-1]
            parts = body.split(",")
            if len(parts) >= 5:
                with self.lock:
                    self.latest_telemetry["pitch_deg"] = round(float(parts[0]), 2)
                    self.latest_telemetry["roll_deg"] = round(float(parts[1]), 2)
                    self.latest_telemetry["cell_pressure_v"] = round(float(parts[2]), 2)
                    self.latest_telemetry["chassis_dir"] = int(parts[3])
                    self.latest_telemetry["chassis_speed"] = round(float(parts[4]), 1)
                    self.latest_telemetry["last_rx_time"] = time.time()
        except Exception:
            pass

    def get_telemetry(self) -> Dict[str, Any]:
        with self.lock:
            data = dict(self.latest_telemetry)
        data["arduino_streaming"] = (time.time() - data["last_rx_time"]) < 1.5
        return data

    def send_raw(self, cmd_str: str) -> bool:
        if not self.is_port_open():
            if not self._try_open():
                return False
        try:
            with self.lock:
                self.serial_conn.write(cmd_str.encode("ascii"))
                self.serial_conn.flush()
            return True
        except Exception as e:
            print(f"[UART] Error enviando: {e}")
            return False

    # --- LOCOMOCIÓN (VELOCIDAD CONTINUA EN NANO) ---
    def forward(self) -> bool:
        with self.lock:
            self.latest_telemetry["chassis_dir"] = 1
        return self.send_raw("A\n")

    def reverse(self) -> bool:
        with self.lock:
            self.latest_telemetry["chassis_dir"] = 2
        return self.send_raw("R\n")

    def stop(self) -> bool:
        with self.lock:
            self.latest_telemetry["chassis_dir"] = 0
        return self.send_raw("S\n")

    # --- PISTÓN MANUAL (MANTENER / SOLTAR) ---
    def extend_piston(self) -> bool:
        return self.send_raw("E\n")

    def retract_piston(self) -> bool:
        return self.send_raw("C\n")

    def stop_piston(self) -> bool:
        return self.send_raw("X\n")

    def close(self) -> None:
        self.running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()