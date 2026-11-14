# -*- coding: utf-8 -*-
import cv2
import yaml
import time
import asyncio
import threading
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from core.orchestrator import CoreOrchestrator

with open("config/system_settings.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

app = FastAPI(title="Robot Inspector Tuberías - HMI")
orchestrator = CoreOrchestrator(config)

app.mount("/static", StaticFiles(directory="static"), name="static")

# --- HILO ASÍNCRONO DE CÁMARA CON RECONEXIÓN EN CALIENTE (HOT-PLUG) ---
class CameraStreamThread:
    def __init__(self):
        self.cap = None
        self.latest_jpeg = None
        self.lock = threading.Lock()
        self.running = True
        self._build_placeholder("Iniciando camara...")
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _build_placeholder(self, msg: str):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(img, msg, (110, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 180, 255), 2)
        _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with self.lock:
            self.latest_jpeg = buf.tobytes()

    def _try_connect_camera(self) -> bool:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        for dev_idx in [0, 1, 2, 3]:
            try:
                cap = cv2.VideoCapture(dev_idx, cv2.CAP_V4L2)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    cap.set(cv2.CAP_PROP_FPS, 30)
                    ok, test_frame = cap.read()
                    if ok and test_frame is not None:
                        self.cap = cap
                        print(f"[CAMARA] Conectada en /dev/video{dev_idx}")
                        return True
                cap.release()
            except Exception:
                pass
        return False

    def _capture_loop(self):
        fail_count = 0
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                self._build_placeholder("Esperando conexion de camara...")
                if not self._try_connect_camera():
                    time.sleep(1.0)
                    continue
                fail_count = 0

            ok, frame = self.cap.read()
            if ok and frame is not None:
                fail_count = 0
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                with self.lock:
                    self.latest_jpeg = buf.tobytes()
                time.sleep(0.033)
            else:
                fail_count += 1
                if fail_count >= 5:
                    if self.cap is not None:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                        self.cap = None
                    self._build_placeholder("Reconectando camara...")
                    time.sleep(0.5)
                else:
                    time.sleep(0.1)

    def get_jpeg(self) -> bytes:
        with self.lock:
            return self.latest_jpeg

camera_worker = CameraStreamThread()

async def async_mjpeg_generator():
    while True:
        frame_bytes = camera_worker.get_jpeg()
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
        await asyncio.sleep(0.04)

# --- MODELOS DE DATOS ---
class ModeCmd(BaseModel):
    automatic: bool

class LaserToggleCmd(BaseModel):
    enabled: bool
    power_pct: float = 60.0

class LaserPwmCmd(BaseModel):
    power_pct: float

class MotorCmd(BaseModel):
    direction: str
    speed_pct: float

# --- RUTAS DE LA APLICACIÓN ---
@app.get("/")
async def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/video_feed")
async def video_feed():
    return StreamingResponse(
        async_mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/state")
async def get_state():
    return orchestrator.get_full_state()

# --- LOCOMOCIÓN (ARDUINO NANO) ---
@app.post("/api/chassis/forward")
async def chassis_forward():
    ok = orchestrator.uart.forward()
    return {"ok": ok, "state": orchestrator.get_full_state()}

@app.post("/api/chassis/reverse")
async def chassis_reverse():
    ok = orchestrator.uart.reverse()
    return {"ok": ok, "state": orchestrator.get_full_state()}

@app.post("/api/chassis/stop")
async def chassis_stop():
    ok = orchestrator.uart.stop()
    return {"ok": ok, "state": orchestrator.get_full_state()}

@app.post("/api/chassis/mode")
async def set_chassis_mode(cmd: ModeCmd):
    orchestrator.chassis_mode_auto = bool(cmd.automatic)
    if not orchestrator.chassis_mode_auto:
        orchestrator.uart.stop()
    return {"ok": True, "state": orchestrator.get_full_state()}

# --- PISTÓN MANUAL (ARDUINO NANO) ---
@app.post("/api/piston/extend")
async def piston_extend():
    ok = orchestrator.uart.extend_piston()
    return {"ok": ok, "state": orchestrator.get_full_state()}

@app.post("/api/piston/retract")
async def piston_retract():
    ok = orchestrator.uart.retract_piston()
    return {"ok": ok, "state": orchestrator.get_full_state()}

@app.post("/api/piston/stop")
async def piston_stop():
    ok = orchestrator.uart.stop_piston()
    return {"ok": ok, "state": orchestrator.get_full_state()}

# --- LÁSER Y MOTOR N20 (PCA9685) ---
@app.post("/api/laser/toggle")
async def toggle_laser(cmd: LaserToggleCmd):
    ok = orchestrator.laser_ctl.set_laser_state(cmd.enabled, cmd.power_pct)
    return {"ok": ok, "state": orchestrator.get_full_state()}

@app.post("/api/laser/pwm")
async def set_laser_pwm(cmd: LaserPwmCmd):
    ok = orchestrator.laser_ctl.set_laser_pwm(cmd.power_pct)
    return {"ok": ok, "state": orchestrator.get_full_state()}

@app.post("/api/laser/motor")
async def control_laser_motor(cmd: MotorCmd):
    ok = orchestrator.laser_ctl.set_motor(cmd.direction, cmd.speed_pct)
    return {"ok": ok, "state": orchestrator.get_full_state()}

@app.post("/api/laser/home")
async def reset_laser_home():
    orchestrator.encoder.reset_home()
    return {"ok": True, "state": orchestrator.get_full_state()}

# --- WEBSOCKET TELEMETRÍA ---
@app.websocket("/ws/telemetry")
async def websocket_telemetry(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(orchestrator.get_full_state())
            await asyncio.sleep(0.15)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass