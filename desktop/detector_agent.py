"""Windows gate detector agent for VISION AI - SRM TRP.

The agent runs the existing local vision cascade and posts only identified
events to the transport API. It is intentionally separate from the web portal:
the gate computer owns the camera and AI workload, while Render owns storage.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import cv2
import requests
import pystray
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.vision import best_identification, detect


CONFIG_DIR = Path(os.getenv("APPDATA", Path.home())) / "VisionAI" / "GateAgent"
CONFIG_PATH = CONFIG_DIR / "settings.json"
LOG_PATH = CONFIG_DIR / "agent.log"
DEFAULT_API_URL = "https://srm-trp-transport.onrender.com"


@dataclass
class AgentSettings:
    api_url: str = DEFAULT_API_URL
    gate: str = "Gate 1"
    camera_id: str = "gate-1-entry"
    direction: str = "IN"
    camera_index: int = 0
    interval_seconds: float = 1.0


def load_settings() -> AgentSettings:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        allowed = {field: payload[field] for field in asdict(AgentSettings()) if field in payload}
        return AgentSettings(**allowed)
    except (OSError, ValueError, TypeError):
        return AgentSettings()


def save_settings(settings: AgentSettings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


class DetectorWorker:
    def __init__(self, settings: AgentSettings, device_key: str, emit) -> None:
        self.settings = settings
        self.device_key = device_key
        self.emit = emit
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_sent: dict[str, float] = {}

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="vision-agent", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        capture = cv2.VideoCapture(self.settings.camera_index)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        if not capture.isOpened():
            self.emit("ERROR", f"Could not open camera {self.settings.camera_index}.")
            return

        self.emit("INFO", "Camera started.")
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                ok, frame = capture.read()
                if not ok or frame is None:
                    self.emit("ERROR", "Camera returned no frame.")
                else:
                    self._scan(frame)
                delay = max(0.1, self.settings.interval_seconds - (time.monotonic() - started))
                self.stop_event.wait(delay)
        finally:
            capture.release()
            self.emit("INFO", "Camera stopped.")

    def _scan(self, frame) -> None:
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            result = detect(image)
            candidate = best_identification(result)
            vehicle = result.vehicle or {}
            label = vehicle.get("label") or "unknown"
            if label != "bus":
                self.emit("INFO", f"Non-bus ignored: {label}.")
                return
            if candidate and candidate.bus_number:
                bus_number = candidate.bus_number
                confidence = float(candidate.confidence)
                key = f"{bus_number}|{self.settings.gate}|{self.settings.direction}"
                now = time.monotonic()
                if now - self.last_sent.get(key, 0) < 30:
                    self.emit("INFO", f"Duplicate suppressed: {bus_number} ({label}).")
                    return
                self.last_sent[key] = now
                self._post_event(bus_number, confidence, label, result.cascade, result.inference_ms)
            else:
                self.emit("SCAN", f"No number read; vehicle={label}; reason={result.reason}.")
        except Exception as exc:
            self.emit("ERROR", f"Detection failed: {type(exc).__name__}: {exc}")

    def _post_event(
        self,
        bus_number: str,
        confidence: float,
        vehicle: str,
        detection_stage: str,
        inference_ms: int,
    ) -> None:
        if not self.device_key:
            self.emit("ERROR", "Device API key is required before starting.")
            return
        payload = {
            "bus_number": bus_number,
            "direction": self.settings.direction,
            "gate": self.settings.gate,
            "camera_id": self.settings.camera_id,
            "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        try:
            response = requests.post(
                f"{self.settings.api_url.rstrip('/')}/api/events",
                json=payload,
                headers={"X-Device-Key": self.device_key},
                timeout=10,
            )
            if response.ok:
                self.emit(
                    "EVENT",
                    f"{bus_number} / {vehicle} via {detection_stage} uploaded ({inference_ms} ms).",
                )
            else:
                self.emit("ERROR", f"API rejected event: HTTP {response.status_code}.")
        except requests.RequestException as exc:
            self.emit("ERROR", f"API unavailable: {type(exc).__name__}.")


class GateAgentApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("VISION AI - SRM TRP | Gate Agent")
        self.root.geometry("680x620")
        self.root.minsize(620, 520)
        self.settings = load_settings()
        self.worker: DetectorWorker | None = None
        self.tray: pystray.Icon | None = None
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.vars = {
            "api_url": tk.StringVar(value=self.settings.api_url),
            "device_key": tk.StringVar(value=os.getenv("VISION_DEVICE_API_KEY", "")),
            "gate": tk.StringVar(value=self.settings.gate),
            "camera_id": tk.StringVar(value=self.settings.camera_id),
            "direction": tk.StringVar(value=self.settings.direction),
            "camera_index": tk.StringVar(value=str(self.settings.camera_index)),
            "interval": tk.StringVar(value=str(self.settings.interval_seconds)),
            "status": tk.StringVar(value="Ready to start"),
        }
        self._build_ui()
        self.root.after(200, self._drain_messages)
        self.root.protocol("WM_DELETE_WINDOW", self._hide_window)
        self._start_tray()

    def _build_ui(self) -> None:
        self.root.configure(bg="#f7f3ff")
        header = tk.Frame(self.root, bg="#33145f", padx=24, pady=20)
        header.pack(fill="x")
        tk.Label(header, text="VISION AI - SRM TRP", fg="white", bg="#33145f",
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(header, text="Gate detection agent", fg="#f2d488", bg="#33145f",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

        content = ttk.Frame(self.root, padding=24)
        content.pack(fill="both", expand=True)
        form = ttk.LabelFrame(content, text="Connection and gate setup", padding=16)
        form.pack(fill="x")
        fields = [
            ("Render API URL", "api_url"),
            ("Device API key", "device_key"),
            ("Gate", "gate"),
            ("Camera ID", "camera_id"),
            ("Camera index", "camera_index"),
            ("Scan interval (seconds)", "interval"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            show = "*" if key == "device_key" else ""
            ttk.Entry(form, textvariable=self.vars[key], show=show, width=48).grid(
                row=row, column=1, sticky="ew", pady=5
            )
        ttk.Label(form, text="Direction").grid(row=4, column=2, sticky="w", padx=(18, 8), pady=5)
        ttk.Combobox(form, textvariable=self.vars["direction"], values=("IN", "OUT"),
                     state="readonly", width=10).grid(row=4, column=3, sticky="w", pady=5)
        form.columnconfigure(1, weight=1)

        actions = ttk.Frame(content, padding=(0, 16, 0, 10))
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="Start detection", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="Stop", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Save settings", command=self._save).pack(side="left")
        ttk.Label(actions, textvariable=self.vars["status"]).pack(side="right")

        log_frame = ttk.LabelFrame(content, text="Agent activity", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=14, state="disabled", wrap="word",
                           bg="#201433", fg="#f7f3ff", insertbackground="white")
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)

    def _start_tray(self) -> None:
        image = Image.new("RGB", (64, 64), "#33145f")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#c9a227")
        draw.text((22, 17), "V", fill="#33145f")
        menu = pystray.Menu(
            pystray.MenuItem("Open agent", lambda *_: self.root.after(0, self._show_window)),
            pystray.MenuItem("Start detection", lambda *_: self.root.after(0, self._start)),
            pystray.MenuItem("Stop detection", lambda *_: self.root.after(0, self._stop)),
            pystray.MenuItem("Quit", lambda *_: self.root.after(0, self._quit)),
        )
        self.tray = pystray.Icon("vision-ai-gate-agent", image, "VISION AI - SRM TRP", menu)
        threading.Thread(target=self.tray.run, name="tray", daemon=True).start()

    def _read_settings(self) -> AgentSettings:
        return AgentSettings(
            api_url=self.vars["api_url"].get().strip(),
            gate=self.vars["gate"].get().strip(),
            camera_id=self.vars["camera_id"].get().strip(),
            direction=self.vars["direction"].get().strip().upper(),
            camera_index=int(self.vars["camera_index"].get()),
            interval_seconds=max(0.5, float(self.vars["interval"].get())),
        )

    def _save(self) -> None:
        try:
            save_settings(self._read_settings())
            self.vars["status"].set("Settings saved")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Could not save settings", str(exc))

    def _start(self) -> None:
        try:
            settings = self._read_settings()
        except ValueError:
            messagebox.showerror("Invalid setup", "Camera index and scan interval must be numbers.")
            return
        if not settings.api_url or not settings.gate or not settings.camera_id:
            messagebox.showerror("Incomplete setup", "API URL, gate, and camera ID are required.")
            return
        if not self.vars["device_key"].get().strip():
            messagebox.showerror("Missing device key", "Enter the device API key from Render before starting.")
            return
        self._save()
        self.worker = DetectorWorker(settings, self.vars["device_key"].get().strip(), self._queue_message)
        self.worker.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.vars["status"].set("Running")

    def _stop(self) -> None:
        if self.worker:
            self.worker.stop()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.vars["status"].set("Stopped")

    def _queue_message(self, level: str, message: str) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                stamp = datetime.now().isoformat(timespec="seconds")
                handle.write(f"[{stamp}] {level}: {message}\n")
        except OSError:
            pass
        self.messages.put((level, message))

    def _drain_messages(self) -> None:
        while True:
            try:
                level, message = self.messages.get_nowait()
            except queue.Empty:
                break
            stamp = datetime.now().strftime("%H:%M:%S")
            self.log.configure(state="normal")
            self.log.insert("end", f"[{stamp}] {level}: {message}\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(200, self._drain_messages)

    def _hide_window(self) -> None:
        self.root.withdraw()

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _quit(self) -> None:
        self._stop()
        if self.tray:
            self.tray.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    GateAgentApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
