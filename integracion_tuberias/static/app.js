let ws = null;
let isAutoMode = false;
let isLaserEnabled = false;
let currentMotorDir = "STOP";
let laserDebounceTimer = null;
let isPistonMoving = false;

document.addEventListener("DOMContentLoaded", () => {
    connectWebSocket();
    setupKeyboardControl();
    setupPistonButtons();
    setInterval(pollStateFallback, 1000);
});

function showActionStatus(msg, isError = false) {
    const badge = document.getElementById("last-cmd-badge");
    if (!badge) return;
    badge.innerText = msg;
    badge.className = isError ? "badge badge-err" : "badge badge-ok";
}

// 1. CONEXIÓN WEBSOCKET Y POLLING DE RESPALDO
function connectWebSocket() {
    const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
    ws = new WebSocket(`${proto}${window.location.host}/ws/telemetry`);

    ws.onopen = () => {
        const b = document.getElementById("ws-badge");
        b.innerText = "EN LÍNEA (TIEMPO REAL)";
        b.className = "badge badge-ok";
    };

    ws.onmessage = (event) => {
        try {
            const state = JSON.parse(event.data);
            updateUI(state);
        } catch (err) {
            console.error("Error WS:", err);
        }
    };

    ws.onclose = () => {
        const b = document.getElementById("ws-badge");
        b.innerText = "RECONECTANDO...";
        b.className = "badge badge-warn";
        setTimeout(connectWebSocket, 1500);
    };
}

async function pollStateFallback() {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    try {
        const res = await fetch("/api/state");
        if (res.ok) {
            const state = await res.json();
            updateUI(state);
        }
    } catch (e) {}
}

// 2. ACTUALIZACIÓN VISUAL DE LA PÁGINA WEB
function updateUI(st) {
    if (!st) return;

    if (st.hardware_health) {
        setPill("st-i2c", st.hardware_health.bus_i2c);
        setPill("st-pca", st.hardware_health.pwm_pca9685);
        setPill("st-ina", st.hardware_health.sensor_ina219);
        setPill("st-uart", st.hardware_health.uart_locomotion);
        setPill("st-enc", st.hardware_health.encoder_hall);
    }

    setText("val-v", `${Number(st.voltage_v || 0).toFixed(2)} V`);
    setText("val-i", `${Number(st.current_ma || 0).toFixed(1)} mA`);
    setText("val-p", `${Number(st.power_mw || 0).toFixed(1)} mW`);
    setText("val-e", `${Number(st.energy_j || 0).toFixed(1)} J`);
    setText("val-temp", `${Number(st.cpu_temp_c || 0).toFixed(1)} °C`);
    setText("val-ard-rx", st.arduino_streaming ? "ARDUINO ONLINE" : "SIN SEÑAL NANO");

    const pitch = Number(st.pitch_deg || 0).toFixed(2);
    const roll = Number(st.roll_deg || 0).toFixed(2);
    setText("val-pitch", `${pitch}°`);
    setText("val-roll", `${roll}°`);
    setText("val-press", `${Number(st.cell_pressure_v || 0).toFixed(2)} V`);
    setText("val-speed", `${Number(st.chassis_speed || 150.0).toFixed(1)}`);

    let dirText = "DETENIDO";
    if (st.chassis_dir === 1) dirText = "ADELANTE ▲";
    if (st.chassis_dir === 2) dirText = "ATRÁS ▼";
    setText("val-dir", dirText);
    setText("hud-dir", `MARCHA: ${dirText}`);
    setText("hud-pitch", `PITCH: ${pitch}° | ROLL: ${roll}°`);

    document.getElementById("btn-fwd").classList.toggle("btn-selected", st.chassis_dir === 1);
    document.getElementById("btn-stop").classList.toggle("btn-selected", st.chassis_dir === 0);
    document.getElementById("btn-rev").classList.toggle("btn-selected", st.chassis_dir === 2);

    isAutoMode = Boolean(st.mode_auto);
    document.getElementById("btn-mode-manual").className = isAutoMode ? "btn" : "btn btn-active";
    document.getElementById("btn-mode-auto").className = isAutoMode ? "btn btn-active" : "btn";

    isLaserEnabled = Boolean(st.laser_enabled);
    const laserBtn = document.getElementById("btn-laser-toggle");
    if (laserBtn) {
        laserBtn.innerText = isLaserEnabled ? "LÁSER: ENCENDIDO" : "LÁSER: APAGADO";
        laserBtn.className = isLaserEnabled ? "btn btn-green btn-selected" : "btn btn-danger";
    }

    currentMotorDir = st.laser_motor_dir || "STOP";
    document.getElementById("btn-m-cw").classList.toggle("btn-selected", currentMotorDir === "FORWARD");
    document.getElementById("btn-m-stop").classList.toggle("btn-selected", currentMotorDir === "STOP");
    document.getElementById("btn-m-ccw").classList.toggle("btn-selected", currentMotorDir === "BACKWARD");
    setText("val-angle", `${Number(st.laser_angle_deg || 0).toFixed(1)}°`);
}

function setText(id, txt) {
    const el = document.getElementById(id);
    if (el) el.innerText = txt;
}

function setPill(id, status) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerText = status;
    el.className = status === "OK" ? "hw-pill pill-ok" : "hw-pill pill-fail";
}

// 3. COMANDOS HTTP
async function postJSON(url, payload = {}) {
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.state) updateUI(data.state);
        return data.ok;
    } catch (e) {
        showActionStatus("ERROR DE RED", true);
        return false;
    }
}

// 4. CONTROL DE LOCOMOCIÓN (AVANZAR / RETROCEDER / STOP / MODO)
async function commandMotion(action) {
    const ok = await postJSON(`/api/chassis/${action}`);
    showActionStatus(ok ? `CMD: ${action.toUpperCase()}` : "FALLO UART3", !ok);
}

async function setMode(auto) {
    await postJSON("/api/chassis/mode", { automatic: auto });
    showActionStatus(auto ? "MODO: AUTOMÁTICO" : "MODO: MANUAL");
}

function setupKeyboardControl() {
    window.addEventListener("keydown", (e) => {
        if (e.target.tagName === "INPUT" || e.repeat) return;
        const k = e.key.toLowerCase();
        if (k === "w" || e.key === "ArrowUp") {
            commandMotion("forward");
        } else if (k === "s" || e.key === "ArrowDown") {
            commandMotion("reverse");
        } else if (k === " " || k === "x") {
            e.preventDefault();
            commandMotion("stop");
        }
    });

    window.addEventListener("keyup", (e) => {
        if (e.target.tagName === "INPUT" || isAutoMode) return;
        const k = e.key.toLowerCase();
        if (["w", "s", "arrowup", "arrowdown"].includes(k)) {
            commandMotion("stop");
        }
    });
}

// 5. BOTONES DEL PISTÓN (MANTENER PRESIONADO PARA MOVER / SOLTAR PARA PARAR)
function setupPistonButtons() {
    const btnExt = document.getElementById("btn-piston-ext");
    const btnRet = document.getElementById("btn-piston-ret");

    if (!btnExt || !btnRet) return;

    const startPiston = (action) => {
        if (isPistonMoving) return;
        isPistonMoving = true;
        postJSON(`/api/piston/${action}`);
        showActionStatus(action === "extend" ? "ESTIRANDO PISTÓN..." : "COMPRIMIENDO PISTÓN...");
    };

    const stopPiston = () => {
        if (!isPistonMoving) return;
        isPistonMoving = false;
        postJSON("/api/piston/stop");
        showActionStatus("PISTÓN RETENIDO");
    };

    // Estirar pistón
    btnExt.addEventListener("mousedown", () => startPiston("extend"));
    btnExt.addEventListener("mouseup", stopPiston);
    btnExt.addEventListener("mouseleave", stopPiston);
    btnExt.addEventListener("touchstart", (e) => { e.preventDefault(); startPiston("extend"); });
    btnExt.addEventListener("touchend", (e) => { e.preventDefault(); stopPiston(); });

    // Comprimir pistón
    btnRet.addEventListener("mousedown", () => startPiston("retract"));
    btnRet.addEventListener("mouseup", stopPiston);
    btnRet.addEventListener("mouseleave", stopPiston);
    btnRet.addEventListener("touchstart", (e) => { e.preventDefault(); startPiston("retract"); });
    btnRet.addEventListener("touchend", (e) => { e.preventDefault(); stopPiston(); });
}

// 6. CONTROL DE LÁSER Y MOTOR
async function toggleLaser() {
    const nextState = !isLaserEnabled;
    const slider = document.getElementById("rng-laser-pwm");
    const pwm = slider ? parseFloat(slider.value) : 60.0;
    const ok = await postJSON("/api/laser/toggle", { enabled: nextState, power_pct: pwm });
    showActionStatus(ok ? (nextState ? "LÁSER ON" : "LÁSER OFF") : "FALLO PCA9685", !ok);
}

function changeLaserPwm(val) {
    setText("lbl-laser-pwm", `${val}%`);
    clearTimeout(laserDebounceTimer);
    laserDebounceTimer = setTimeout(async () => {
        await postJSON("/api/laser/pwm", { power_pct: parseFloat(val) });
    }, 80);
}

function changeMotorPwm(val) {
    setText("lbl-motor-pwm", `${val}%`);
    if (currentMotorDir !== "STOP") {
        clearTimeout(laserDebounceTimer);
        laserDebounceTimer = setTimeout(async () => {
            await postJSON("/api/laser/motor", {
                direction: currentMotorDir,
                speed_pct: parseFloat(val)
            });
        }, 80);
    }
}

async function commandLaserMotor(dir) {
    const slider = document.getElementById("rng-motor-pwm");
    const spd = slider ? parseFloat(slider.value) : 40.0;
    const ok = await postJSON("/api/laser/motor", { direction: dir, speed_pct: spd });
    showActionStatus(ok ? `MOTOR: ${dir}` : "FALLO PCA9685", !ok);
}

async function resetEncoderHome() {
    await postJSON("/api/laser/home");
    showActionStatus("ENCODER EN 0°");
}