#!/usr/bin/env python3
"""rgbman GUI - local web panel (http://127.0.0.1:8765) on top of rgbman.

  python rgbman_gui.py                 start and open the panel in the browser
  python rgbman_gui.py --no-browser    run in background (used by autostart)
  python rgbman_gui.py --install-autostart / --remove-autostart   (admin shell)

Runs until closed. Static colors stay after closing; animated effects stop.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import rgbman

HERE = Path(__file__).resolve().parent
UI_FILE = HERE / "gui.html"
STATE_FILE = HERE / "gui_state.json"
PREVIEW_MAX = 48

DEFAULT_SETTINGS = {"effect": "static", "color": "00b4ff", "speed": 1.0,
                    "brightness": 1.0, "power": True}


class Engine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()
        state = rgbman.load_json(STATE_FILE, {})
        self.settings = {**DEFAULT_SETTINGS, **state.get("settings", {})}
        self.enabled = state.get("enabled", {})      # device name -> bool
        self.devices = []
        self.preview = {}                            # device name -> [hex]
        self.errors = {}
        self.pending = set()                         # names needing a push
        self.scanning = False

    # ------------------------------------------------ state
    def save_state(self):
        STATE_FILE.write_text(json.dumps({"settings": self.settings, "enabled": self.enabled},
                                         indent=2), encoding="utf-8")

    def update_settings(self, patch):
        with self.lock:
            for k in DEFAULT_SETTINGS:
                if k in patch:
                    self.settings[k] = patch[k]
            self.pending = {d.name for d in self.devices}
            self.save_state()

    def set_enabled(self, name, on):
        with self.lock:
            self.enabled[name] = bool(on)
            self.pending.add(name)
            self.save_state()

    def rescan(self, wait=0):
        with self.lock:
            if self.scanning:
                return
            self.scanning = True
            old, self.devices = self.devices, []
        for d in old:
            d.close()
        found = rgbman.discover(self.cfg, wait)
        for d in found:
            try:
                d.prepare()
            except Exception as e:
                self.errors[d.name] = str(e)
        with self.lock:
            self.devices = found
            for d in found:
                self.enabled.setdefault(d.name, True)
            self.pending = {d.name for d in found}
            self.scanning = False

    # ------------------------------------------------ profiles
    def profiles(self):
        return rgbman.load_json(rgbman.PROFILES_FILE, {})

    def save_profile(self, name):
        p = self.profiles()
        with self.lock:
            on = [n for n, v in self.enabled.items() if v and any(d.name == n for d in self.devices)]
            p[name] = {**{k: self.settings[k] for k in ("effect", "color", "speed", "brightness")},
                       "device": on}
        rgbman.PROFILES_FILE.write_text(json.dumps(p, indent=2), encoding="utf-8")

    def apply_profile(self, name):
        p = self.profiles().get(name)
        if not p:
            return
        with self.lock:
            if p.get("device"):
                wanted = [f.lower() for f in p["device"]]
                for d in self.devices:
                    self.enabled[d.name] = any(f in d.name.lower() for f in wanted)
        self.update_settings({**p, "power": True})

    def delete_profile(self, name):
        p = self.profiles()
        p.pop(name, None)
        rgbman.PROFILES_FILE.write_text(json.dumps(p, indent=2), encoding="utf-8")

    # ------------------------------------------------ render loop
    def loop(self):
        t0 = time.monotonic()
        last = {}
        while True:
            now = time.monotonic()
            with self.lock:
                s = dict(self.settings)
                devices = list(self.devices)
                pending, self.pending = self.pending, set()
                enabled = dict(self.enabled)
            base = rgbman.parse_hex(s["color"])
            for d in devices:
                on = s["power"] and enabled.get(d.name, True)
                animated = on and s["effect"] != "static" and d.max_fps > 0
                if animated:
                    if now - last.get(d.name, 0) < 1 / d.max_fps:
                        continue
                elif d.name not in pending:
                    continue
                last[d.name] = now
                n = d.led_count
                if not on:
                    colors = [(0, 0, 0)] * n
                elif animated:
                    colors = [rgbman.frame(s["effect"], now - t0, i, n, base, s["speed"]) for i in range(n)]
                else:
                    colors = [base] * n
                colors = [rgbman.scale(c, s["brightness"]) for c in colors]
                try:
                    d.set_leds(colors)
                    self.errors.pop(d.name, None)
                except Exception as e:
                    self.errors[d.name] = str(e)
                step = max(1, n // PREVIEW_MAX)
                self.preview[d.name] = ["%02x%02x%02x" % c for c in colors[::step][:PREVIEW_MAX]]
            time.sleep(1 / rgbman.FPS)

    def snapshot(self):
        with self.lock:
            return {
                "settings": self.settings,
                "scanning": self.scanning,
                "effects": rgbman.EFFECTS,
                "profiles": list(self.profiles()),
                "devices": [{"name": d.name, "backend": d.backend, "leds": d.led_count,
                             "animated": d.max_fps > 0,
                             "enabled": self.enabled.get(d.name, True),
                             "preview": self.preview.get(d.name, []),
                             "error": self.errors.get(d.name)} for d in self.devices],
            }


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self.send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self.send(200, engine.snapshot())
            else:
                self.send(404, {"error": "not found"})

        def do_POST(self):
            # reject cross-site requests: only the panel itself may change lights
            origin = self.headers.get("Origin", "")
            if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
                return self.send(403, {"error": "forbidden"})
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            routes = {
                "/api/settings": lambda: engine.update_settings(body),
                "/api/device": lambda: engine.set_enabled(body["name"], body["enabled"]),
                "/api/rescan": lambda: threading.Thread(target=engine.rescan, daemon=True).start(),
                "/api/profile/save": lambda: engine.save_profile(body["name"]),
                "/api/profile/apply": lambda: engine.apply_profile(body["name"]),
                "/api/profile/delete": lambda: engine.delete_profile(body["name"]),
            }
            fn = routes.get(self.path)
            if not fn:
                return self.send(404, {"error": "not found"})
            try:
                fn()
                self.send(200, engine.snapshot())
            except (KeyError, ValueError) as e:
                self.send(400, {"error": str(e)})

    return Handler


def autostart(install):
    if not install:
        subprocess.run(["schtasks", "/Delete", "/TN", "rgbman", "/F"], check=False)
        return
    pyw = Path(sys.executable).with_name("pythonw.exe")
    tr = f'"{pyw}" "{Path(__file__).resolve()}" --no-browser'
    subprocess.run(["schtasks", "/Create", "/TN", "rgbman", "/SC", "ONLOGON",
                    "/RL", "HIGHEST", "/TR", tr, "/F"], check=True)
    print("rgbman GUI will start in the background at logon")


def main():
    ap = argparse.ArgumentParser(description="rgbman GUI")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--install-autostart", action="store_true")
    ap.add_argument("--remove-autostart", action="store_true")
    a = ap.parse_args()
    if a.install_autostart or a.remove_autostart:
        return autostart(a.install_autostart)

    url = f"http://127.0.0.1:{a.port}/"
    cfg = rgbman.load_json(rgbman.CONFIG_FILE, {})
    engine = Engine(cfg)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(engine))
    except OSError:  # already running: just open the panel
        webbrowser.open(url)
        return

    engine.rescan(wait=90 if a.no_browser else 5)
    threading.Thread(target=engine.loop, daemon=True).start()
    if not a.no_browser:
        webbrowser.open(url)
    rgbman.log(f"panel at {url} (Ctrl+C to quit)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
