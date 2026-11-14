# -*- coding: utf-8 -*-
import threading
import time

class HallEncoderTracker:
    def __init__(self, chip_num: int = 3, pin_a: int = 20, pin_b: int = 1,
                 gear_ratio: float = 298.0, cpr_motor: float = 3.0):
        self.gear_ratio = gear_ratio
        self.cpr_motor = cpr_motor
        self.pulses_per_output_rev = gear_ratio * cpr_motor * 4.0

        self.pulse_count = 0
        self.running = True
        self.is_available = False
        self.lock = threading.Lock()

        self.worker = threading.Thread(
            target=self._monitor_edges,
            args=(chip_num, pin_a, pin_b),
            daemon=True
        )
        self.worker.start()

    def _monitor_edges(self, chip_num: int, pin_a: int, pin_b: int) -> None:
        chip_path = f"/dev/gpiochip{chip_num}"
        try:
            import gpiod

            # Compatibilidad gpiod v2.x y v1.x
            if hasattr(gpiod, "request_lines"):
                # gpiod versión 2.x
                from gpiod.line import Direction, Edge, Value
                self.is_available = True
                with gpiod.request_lines(
                    chip_path,
                    consumer="hall_encoder",
                    config={
                        pin_a: gpiod.LineSettings(edge_detection=Edge.BOTH),
                        pin_b: gpiod.LineSettings(direction=Direction.INPUT),
                    },
                ) as request:
                    while self.running:
                        if request.wait_edge_events(timeout=0.2):
                            for event in request.read_edge_events():
                                val_b = request.get_value(pin_b)
                                with self.lock:
                                    if event.event_type == event.Type.RISING_EDGE:
                                        self.pulse_count += 1 if val_b == Value.INACTIVE else -1
                                    elif event.event_type == event.Type.FALLING_EDGE:
                                        self.pulse_count += 1 if val_b == Value.ACTIVE else -1
            else:
                # gpiod versión 1.x
                chip = gpiod.Chip(chip_path)
                line_a = chip.get_line(pin_a)
                line_b = chip.get_line(pin_b)

                line_a.request(consumer="enc_a", type=gpiod.LINE_REQ_EV_BOTH_EDGES)
                line_b.request(consumer="enc_b", type=gpiod.LINE_REQ_DIR_IN)
                self.is_available = True

                while self.running:
                    if line_a.event_wait(sec=0, nsec=200_000_000):
                        ev = line_a.event_read()
                        val_b = line_b.get_value()
                        with self.lock:
                            if ev.type == gpiod.LineEvent.RISING_EDGE:
                                self.pulse_count += 1 if val_b == 0 else -1
                            elif ev.type == gpiod.LineEvent.FALLING_EDGE:
                                self.pulse_count += 1 if val_b == 1 else -1

                line_a.release()
                line_b.release()
                chip.close()
        except Exception as e:
            print(f"[Encoder] Error inicializando gpiod en {chip_path}: {e}")
            self.is_available = False
            while self.running:
                time.sleep(1.0)

    def get_angle_deg(self) -> float:
        with self.lock:
            return round((self.pulse_count / self.pulses_per_output_rev) * 360.0, 1)

    def reset_home(self) -> None:
        with self.lock:
            self.pulse_count = 0

    def stop(self) -> None:
        self.running = False