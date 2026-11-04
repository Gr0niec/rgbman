
from __future__ import annotations

import argparse
import datetime
import functools
import json
import re
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent

# pythonw has no console: send output and tracebacks to rgbman.log instead of nowhere
if sys.stderr is None or sys.stdout is None:
    sys.stdout = sys.stderr = open(HERE / "rgbman.log", "a", encoding="utf-8", buffering=1)
    print(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')}")


def fatal(msg):
    print(msg, file=sys.stderr)
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, msg[-1500:], "rgbman - błąd startu", 0x10)


try:
    import pystray
    import webview
    from PIL import Image, ImageDraw

    import rgbman
    import rgbman_i18n
    import rgbman_win
except Exception:
    import traceback
    fatal(traceback.format_exc())
    sys.exit(1)

UI_FILE = HERE / "gui.html"
STATE_FILE = HERE / "gui_state.json"
LOCK_PORT = 47651          # single-instance lock + "show window" signal, localhost only
PREVIEW_MAX = 128  # LEDs per device sent to the panel; it draws zones when it has them all

APP_SCRIPT = Path(__file__).resolve()

DEFAULT_SETTINGS = {"effect": "static", "color": "00b4ff", "color2": "000000",
                    "speed": 1.0, "brightness": 1.0, "power": True}
# per-device overrides of the global look: own effect/color, LED layout, time lead
DEFAULT_DEVICE_FX = {"effect": None, "color": None, "layout": "zones", "lead_ms": 0,
                     "max_fps": 0}  # 0 = the device's own limit
LEAD_MAX_MS = 300
FPS_MIN, FPS_MAX = 5, 60
MODE_CHECK_S = 3  # how often to verify OpenRGB still has our controllers in Direct mode
EFFECT_GROUP = {e: g for g, _, effects in rgbman.EFFECT_GROUPS for e in effects}
EFFECT_HINTS = {
    "audio": "Reaguje na dźwięk z domyślnego wyjścia audio Windows.",
    "ambilight": "Kolory z głównego ekranu, od lewej do prawej. Gry w pełnym ekranie (exclusive) "
                 "mogą dawać czarny obraz: przełącz je na okno bez ramki.",
    "storm": "Drugi kolor to niebo (czarny = granat), pierwszy barwi błyskawice.",
}
# app behavior, edited in the settings dialog; autostart lives in Task Scheduler, not here
DEFAULT_APP = {"close_to_tray": True, "off_when_locked": False, "off_on_exit": False,
               "start_openrgb": False, "openrgb_path": "", "fps": 30,
               "schedule": [],  # [{"time": "HH:MM", "profile": name or OFF_ACTION}]
               "lang": "pl"}
LANGS = ("pl", "en")
OFF_ACTION = "__off__"  # schedule entry that turns the lights off instead of applying a profile
SCHEDULE_MAX = 20


_lang = {"code": "pl"}  # set by the Engine from its settings


def tr(text, **kw):
    """Text in the UI language (Polish source, English from rgbman_i18n), then formatted."""
    out = rgbman_i18n.EN.get(text, text) if _lang["code"] == "en" else text
    return out.format(**kw) if kw else out


def device_layout(d):
    """Zones as the panel draws them: a fan ring, a strip, or a single LED dot."""
    names = list(d.zone_names) or [d.name]
    out = []
    for name, n in zip(names, d.segments or [d.led_count]):
        shape = "dot" if n == 1 else "ring" if d.kind == "motherboard" and 4 <= n <= 24 else "bar"
        out.append({"name": name, "leds": n, "shape": shape})
    return out


def clean_schedule(entries):
    """Keep well-formed {time: "HH:MM", profile} entries, sorted by time."""
    out = []
    for e in entries if isinstance(entries, list) else []:
        t, prof = (e.get("time"), e.get("profile")) if isinstance(e, dict) else (None, None)
        if isinstance(t, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t) and isinstance(prof, str) and prof:
            out.append({"time": t, "profile": prof})
    return sorted(out, key=lambda e: e["time"])[:SCHEDULE_MAX]


def due_entry(schedule, now, since):
    """The entry whose time fell in (since, now] (datetimes); the latest one if several."""
    hit = None
    for e in schedule:
        h, m = map(int, e["time"].split(":"))
        for day in (now.date(), since.date()):  # a window can span midnight
            at = datetime.datetime.combine(day, datetime.time(h, m))
            if since < at <= now and (hit is None or at > hit[0]):
                hit = (at, e)
    return hit[1] if hit else None


class Engine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()
        state = rgbman.load_json(STATE_FILE, {})
        self.settings = {**DEFAULT_SETTINGS, **state.get("settings", {})}
        if self.settings["effect"] not in rgbman.EFFECTS:
            self.settings["effect"] = "static"
        self.app = {**DEFAULT_APP, **state.get("app", {})}
        self.app["openrgb_path"] = self.app["openrgb_path"] or rgbman_win.find_openrgb()
        self.app["schedule"] = clean_schedule(self.app["schedule"])
        self.app["lang"] = self.app["lang"] if self.app["lang"] in LANGS else "pl"
        _lang["code"] = self.app["lang"]
        try:  # the loop divides by it
            self.app["fps"] = min(max(int(self.app["fps"]), FPS_MIN), FPS_MAX)
        except (TypeError, ValueError):
            self.app["fps"] = DEFAULT_APP["fps"]
        self.enabled = state.get("enabled", {})
        self.device_fx = {}  # device name -> non-default DEFAULT_DEVICE_FX keys
        self.devices, self.preview, self.errors = [], {}, {}
        self.pending = set()
        for name, fx in state.get("device_fx", {}).items():  # validated: the loop trusts these
            try:
                self.set_device_fx(name, fx, save=False)
            except Exception:
                pass
        self.scanning = False
        self.autostart = rgbman_win.autostart_state(APP_SCRIPT)
        self.notices = {}  # source ("openrgb", "autostart", "zone") -> problem shown in the panel
        self.stop, self.stopped = threading.Event(), threading.Event()
        self.changed = threading.Event()  # settings, profiles or schedule changed

    def save_state(self):
        self.changed.set()  # tray menu & co. refresh from their own thread
        STATE_FILE.write_text(json.dumps({"settings": self.settings, "enabled": self.enabled,
                                          "device_fx": self.device_fx, "app": self.app},
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

    def set_device_fx(self, name, patch, save=True):
        fx = {**DEFAULT_DEVICE_FX, **self.device_fx.get(name, {})}
        if "effect" in patch:
            fx["effect"] = patch["effect"] if patch["effect"] in rgbman.EFFECTS else None
        if "color" in patch:
            fx["color"] = "%02x%02x%02x" % rgbman.parse_hex(patch["color"]) if patch["color"] else None
        if "layout" in patch:
            fx["layout"] = "uniform" if patch["layout"] == "uniform" else "zones"
        if "lead_ms" in patch:
            fx["lead_ms"] = min(max(int(patch["lead_ms"]), 0), LEAD_MAX_MS)
        if "max_fps" in patch:
            v = int(patch["max_fps"] or 0)
            fx["max_fps"] = min(max(v, FPS_MIN), FPS_MAX) if v else 0
        with self.lock:
            changed = {k: v for k, v in fx.items() if v != DEFAULT_DEVICE_FX[k]}
            if changed:
                self.device_fx[name] = changed
            else:
                self.device_fx.pop(name, None)
            self.pending.add(name)
            if save:
                self.save_state()

    # ---- app settings
    def update_app(self, patch):
        with self.lock:
            for k, v in DEFAULT_APP.items():
                if k in patch and k != "schedule":
                    self.app[k] = type(v)(patch[k])
            if "schedule" in patch:
                self.app["schedule"] = clean_schedule(patch["schedule"])
            if self.app["lang"] not in LANGS:
                self.app["lang"] = "pl"
            _lang["code"] = self.app["lang"]
            self.app["fps"] = min(max(self.app["fps"], FPS_MIN), FPS_MAX)
            if "start_openrgb" in patch or "openrgb_path" in patch:
                self.notices.pop("openrgb", None)  # re-checked on the next scan
            self.pending = {d.name for d in self.devices}
            self.save_state()

    def set_autostart(self, on):
        try:
            rgbman_win.set_autostart(on, APP_SCRIPT)
            self.notices.pop("autostart", None)
        except OSError as e:
            self.notices["autostart"] = (tr("Windows nie dał zgody, autostart bez zmian.")
                                         if e.winerror == rgbman_win.ERROR_CANCELLED else f"Autostart: {e}")
        self.autostart = rgbman_win.autostart_state(APP_SCRIPT)

    def set_zone_size(self, device, zone, size):
        if self.scanning:
            raise ValueError(tr("trwa skanowanie, spróbuj za chwilę"))
        d = next(d for d in self.devices if d.name == device)
        z = next(z for z in d.resizable if z["name"] == zone)
        size = int(size)
        if not z["min"] <= size <= z["max"]:
            raise ValueError(tr("{zone}: dozwolone {lo}-{hi} LED", zone=zone, lo=z["min"], hi=z["max"]))
        # re-read so hand edits made while the app runs aren't overwritten
        cfg = rgbman.load_json(rgbman.CONFIG_FILE, {})
        cfg.setdefault("openrgb", {}).setdefault("zone_sizes", {}).setdefault(device, {})[zone] = size
        rgbman.CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        self.rescan()  # discover() applies zone_sizes

    def _openrgb_up(self):
        oc = self.cfg.get("openrgb", {})
        return rgbman_win.port_open(oc.get("host", "127.0.0.1"), oc.get("port", 6742))

    def ensure_openrgb(self):
        """Start OpenRGB if the setting is on and its SDK server isn't up.
        True when OpenRGB is (probably) starting, so the scan should wait for it."""
        if not self.app["start_openrgb"] or self._openrgb_up():
            self.notices.pop("openrgb", None)
            return False
        path = self.app["openrgb_path"]
        if path and rgbman_win.process_running(Path(path).name):
            return True  # already starting, or running without the server: checked after the scan
        try:
            rgbman_win.start_openrgb(path)
            self.notices.pop("openrgb", None)
            return True
        except OSError as e:
            self.notices["openrgb"] = (tr("Windows nie dał zgody na uruchomienie OpenRGB.")
                                       if e.winerror == rgbman_win.ERROR_CANCELLED else f"OpenRGB: {tr(str(e))}")
            return False

    def rescan(self, wait=0):
        with self.lock:
            if self.scanning or self.stop.is_set():
                return
            self.scanning = True
            old, self.devices = self.devices, []
        try:
            self._close(old)
            starting = self.ensure_openrgb()
            found = rgbman.discover(self.cfg, max(wait, 30) if starting else wait, settle=starting)
            if starting and not any(d.backend == "openrgb" for d in found) and not self._openrgb_up():
                self.notices["openrgb"] = tr("OpenRGB działa, ale serwer SDK nie odpowiada. "
                                             "Włącz go w OpenRGB: zakładka SDK Server → Start Server.")
            for d in found:
                try:
                    d.prepare()
                except Exception as e:
                    self.errors[d.name] = str(e)
            with self.lock:
                if self.stop.is_set():  # quit while scanning: shutdown() already ran
                    self._off_and_close(found)
                    return
                self.devices = found
                for d in found:
                    self.enabled.setdefault(d.name, True)
                self.pending = {d.name for d in found}
        finally:
            self.scanning = False

    @staticmethod
    def _close(devices):
        for d in devices:  # OpenRGB devices share one client; a second disconnect is harmless
            try:
                d.close()
            except Exception:
                pass

    def _off_and_close(self, devices):
        """Blank first, close after: closing one OpenRGB device disconnects them all."""
        if self.app["off_on_exit"]:
            for d in devices:
                try:
                    d.set_leds([(0, 0, 0)] * d.led_count)
                    rgbman.log(f"off: {d.name}")
                except Exception as e:
                    rgbman.log(f"off failed: {d.name}: {e}")
        self._close(devices)

    # ---- profiles (same profiles.json as the CLI)
    def profiles(self):
        return rgbman.load_json(rgbman.PROFILES_FILE, {})

    def save_profile(self, name):
        p = self.profiles()
        with self.lock:
            on = [d.name for d in self.devices if self.enabled.get(d.name, True)]
            p[name] = {**{k: self.settings[k] for k in ("effect", "color", "color2", "speed", "brightness")},
                       "device": on, "device_fx": json.loads(json.dumps(self.device_fx))}
        rgbman.PROFILES_FILE.write_text(json.dumps(p, indent=2), encoding="utf-8")
        self.changed.set()

    def apply_profile(self, name):
        p = self.profiles().get(name)
        if not p:
            return
        with self.lock:
            if p.get("device"):
                wanted = [f.lower() for f in p["device"]]
                for d in self.devices:
                    self.enabled[d.name] = any(f in d.name.lower() for f in wanted)
            replace_fx = isinstance(p.get("device_fx"), dict)  # older profiles: keep current overrides
            if replace_fx:
                self.device_fx = {}
        if replace_fx:
            for name, fx in p["device_fx"].items():
                try:
                    self.set_device_fx(name, fx, save=False)
                except Exception:
                    pass
        self.update_settings({**p, "power": True})

    def delete_profile(self, name):
        p = self.profiles()
        p.pop(name, None)
        rgbman.PROFILES_FILE.write_text(json.dumps(p, indent=2), encoding="utf-8")
        self.changed.set()

    # ---- schedule
    def run_schedule(self):
        """Apply scheduled profiles. At start, catch up on the latest entry of the last
        24 h, so a PC switched on after 22:00 still gets the 22:00 profile."""
        last = datetime.datetime.now() - datetime.timedelta(days=1)
        while not self.stop.wait(15):
            now = datetime.datetime.now()
            entry = due_entry(self.app["schedule"], now, last)
            last = now
            if entry and not self.stop.is_set():
                rgbman.log(f"schedule {entry['time']}: {entry['profile']}")
                if entry["profile"] == OFF_ACTION:
                    self.update_settings({"power": False})
                else:
                    self.apply_profile(entry["profile"])

    # ---- render loop
    def loop(self):
        t0 = tick = time.monotonic()
        credit = {}  # device name -> frames it is owed; a device at r fps of F gets r/F per tick
        locked, lock_checked = False, 0.0
        mode_checked, mode_error = time.monotonic(), None
        while not self.stop.is_set():
            now = time.monotonic()
            with self.lock:
                s = dict(self.settings)
                devices = list(self.devices)
                pending, self.pending = self.pending, set()
                enabled = dict(self.enabled)
                device_fx = {k: dict(v) for k, v in self.device_fx.items()}
                off_when_locked = self.app["off_when_locked"]
                fps = self.app["fps"]
            if now - lock_checked > 1:
                lock_checked = now
                was, locked = locked, off_when_locked and rgbman_win.screen_locked()
                if locked != was:
                    pending |= {d.name for d in devices}
            # here, not in another thread: OpenRGB devices share one client socket with the writes
            if now - mode_checked > MODE_CHECK_S and not self.scanning:
                mode_checked = now
                try:
                    fixed, changed = rgbman.restore_direct(devices)
                    pending |= {d.name for d in fixed}  # Direct starts black: send the colors again
                    if changed:
                        threading.Thread(target=self.rescan, daemon=True).start()
                    mode_error = None
                except Exception as e:
                    if str(e) != mode_error:  # e.g. OpenRGB closed; the writes report it per device
                        mode_error = str(e)
                        rgbman.log(f"OpenRGB mode check: {e}")
            c1, c2 = rgbman.parse_hex(s["color"]), rgbman.parse_hex(s["color2"])
            for d in devices:
                fx = {**DEFAULT_DEVICE_FX, **device_fx.get(d.name, {})}
                effect = fx["effect"] or s["effect"]
                color = rgbman.parse_hex(fx["color"]) if fx["color"] else c1
                on = s["power"] and not locked and enabled.get(d.name, True)
                animated = on and rgbman.EFFECTS[effect][2] and d.max_fps > 0
                if animated:
                    # evenly spaced frames: 15 of 30 fps is every 2nd tick, not "whenever it fits"
                    rate = min(fx["max_fps"] or d.max_fps, fps)
                    owed = min(credit.get(d.name, 1.0), 2.0)
                    if owed < 1 and d.name not in pending:
                        credit[d.name] = owed + rate / fps
                        continue
                    credit[d.name] = max(owed - 1, 0.0) + rate / fps
                elif d.name not in pending:
                    continue
                n = d.led_count
                if not on:
                    colors = [(0, 0, 0)] * n
                elif d.max_fps > 0:
                    # lead: render a slow device's frames ahead so they land in step with the rest
                    t = now - t0 + fx["lead_ms"] / 1000 if animated else 0
                    colors = rgbman.render(d, effect, t, color, s["speed"], c2, fx["layout"] == "uniform")
                else:  # static-only device
                    colors = [color] * n
                colors = [rgbman.scale(c, s["brightness"]) for c in colors]
                try:
                    d.set_leds(colors)
                    self.errors.pop(d.name, None)
                except Exception as e:
                    self.errors[d.name] = str(e)
                step = max(1, n // PREVIEW_MAX)
                self.preview[d.name] = ["%02x%02x%02x" % c for c in colors[::step][:PREVIEW_MAX]]
            # fixed ticks, not "sleep after the work": work time doesn't stretch the frame period
            tick += 1 / fps
            delay = tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:  # fell behind (slow write, PC busy): restart the clock instead of bursting
                tick = time.monotonic()
        self.stopped.set()

    def shutdown(self, reason="quit"):
        """Stop rendering, then optionally turn everything off. Static colors otherwise stay.
        A scan still running cleans up its own devices when it sees stop (see rescan).
        Safe to call twice (Windows shutdown reaches us through two windows)."""
        with self.lock:
            if self.stop.is_set():
                return
            self.stop.set()
        rgbman.log(f"shutdown ({reason}, {time.strftime('%H:%M:%S')}), lights off: {self.app['off_on_exit']}")
        self.stopped.wait(2)  # never write while the loop is mid-frame on the same socket
        with self.lock:
            devices, self.devices = list(self.devices), []
        self._off_and_close(devices)
        deadline = time.monotonic() + 3
        while self.scanning and time.monotonic() < deadline:
            time.sleep(0.1)

    @staticmethod
    def _source_error(effect):
        """Capture problem of the input the effect reads (system audio or the screen)."""
        if effect in rgbman.AUDIO_EFFECTS:
            return rgbman.AUDIO.error
        return rgbman.SCREEN.error if effect == "ambilight" else None

    def snapshot(self):
        with self.lock:
            return {
                "settings": dict(self.settings),
                "scanning": self.scanning,
                "effects": [{"id": k, "label": tr(v[0]), "color2": v[1], "animated": v[2],
                             "audio": k in rgbman.AUDIO_EFFECTS,
                             "group": EFFECT_GROUP[k],
                             "description": tr(rgbman.EFFECT_INFO[k]),
                             "speed_label": tr(rgbman.SPEED_LABELS.get(k, "Prędkość")),
                             "hint": tr(h) if (h := EFFECT_HINTS.get("audio" if k in rgbman.AUDIO_EFFECTS else k)) else None}
                            for _, _, group in rgbman.EFFECT_GROUPS for k in group
                            for v in [rgbman.EFFECTS[k]]],
                "groups": [{"id": g, "label": tr(label)} for g, label, _ in rgbman.EFFECT_GROUPS],
                "audio_error": self._source_error(self.settings["effect"]),
                "profiles": list(self.profiles()),
                "app": {**self.app, "autostart": self.autostart,
                        "notice": " ".join(self.notices.values()) or None},
                "devices": [{"name": d.name, "backend": d.backend, "leds": d.led_count,
                             "animated": d.max_fps > 0, "max_fps": d.max_fps,
                             "enabled": self.enabled.get(d.name, True),
                             "fx": {**DEFAULT_DEVICE_FX, **self.device_fx.get(d.name, {})},
                             "kind": d.kind, "layout": device_layout(d),
                             "zones": list(d.resizable),
                             "preview": self.preview.get(d.name, []),
                             "error": self.errors.get(d.name)} for d in self.devices],
            }


def _log_errors(cls):
    """pywebview turns an exception in a js_api call into a bare rejected promise; keep
    the traceback in rgbman.log so a "panel error" can be diagnosed afterwards."""
    for name, fn in list(vars(cls).items()):
        if name.startswith("_") or not callable(fn):
            continue

        def wrap(fn):
            @functools.wraps(fn)
            def call(*a, **k):
                try:
                    return fn(*a, **k)
                except Exception:
                    rgbman.log(f"api {fn.__name__} failed:\n{traceback.format_exc()}")
                    raise
            return call

        setattr(cls, name, wrap(fn))
    return cls


@_log_errors
class Api:
    """Methods exposed to gui.html as window.pywebview.api.*"""

    def __init__(self, engine):
        self._engine = engine

    def state(self):
        return self._engine.snapshot()

    def log(self, message):
        rgbman.log(f"panel: {str(message)[:4000]}")

    def translations(self):
        return rgbman_i18n.EN

    def previews(self, color, color2, speed):
        return rgbman.previews(rgbman.parse_hex(color), rgbman.parse_hex(color2), float(speed))

    def settings(self, patch):
        self._engine.update_settings(patch)
        return self.state()

    def device(self, name, enabled):
        self._engine.set_enabled(name, enabled)
        return self.state()

    def device_fx(self, name, patch):
        self._engine.set_device_fx(name, patch)
        return self.state()

    def rescan(self):
        threading.Thread(target=self._engine.rescan, daemon=True).start()
        time.sleep(0.05)
        return self.state()

    def profile_save(self, name):
        self._engine.save_profile(name)
        return self.state()

    def profile_apply(self, name):
        self._engine.apply_profile(name)
        return self.state()

    def profile_delete(self, name):
        self._engine.delete_profile(name)
        return self.state()

    def app_settings(self, patch):
        self._engine.update_app(patch)
        return self.state()

    def autostart(self, on):
        self._engine.set_autostart(on)  # blocks until the UAC prompt is answered
        return self.state()

    def zone_size(self, device, zone, size):
        notices = self._engine.notices
        try:
            self._engine.set_zone_size(device, zone, size)
            notices.pop("zone", None)
        except (StopIteration, ValueError) as e:
            notices["zone"] = tr("Rozmiar strefy: {msg}.", msg=str(e) or tr("urządzenie zniknęło, skanuj ponownie"))
        except OSError as e:
            notices["zone"] = tr("Rozmiar strefy: nie można zapisać config.json ({msg}).", msg=e)
        return self.state()


def tray_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for k, c in enumerate([(255, 0, 64), (0, 230, 118), (0, 180, 255)]):
        d.ellipse((4 + k * 14, 4 + k * 14, 32 + k * 14, 32 + k * 14), fill=c)
    return img


def single_instance(show):
    """Return a listening socket if we are the first instance, else ask it to show itself."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        try:
            with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=2) as c:
                c.sendall(b"show")
        except OSError:
            pass
        return None
    srv.listen(1)

    def serve():
        while True:
            conn, _ = srv.accept()
            with conn:
                if conn.recv(16) == b"show":
                    show()

    threading.Thread(target=serve, daemon=True).start()
    return srv


def autostart(install):
    rgbman_win.set_autostart(install, APP_SCRIPT)
    print("rgbman will start in the tray at logon" if install else "autostart removed")


def main():
    ap = argparse.ArgumentParser(description="rgbman desktop app")
    ap.add_argument("--hidden", action="store_true", help="start in the tray only")
    ap.add_argument("--install-autostart", action="store_true")
    ap.add_argument("--remove-autostart", action="store_true")
    a = ap.parse_args()
    if a.install_autostart or a.remove_autostart:
        return autostart(a.install_autostart)

    holder = {}
    lock = single_instance(lambda: holder["show"]())
    if lock is None:
        return

    engine = Engine(rgbman.load_json(rgbman.CONFIG_FILE, {}))
    window = webview.create_window("rgbman", html=UI_FILE.read_text(encoding="utf-8"),
                                   js_api=Api(engine), width=1180, height=780,
                                   min_size=(760, 560), hidden=a.hidden)
    quitting = threading.Event()

    def show():
        window.show()
        window.restore()

    holder["show"] = show

    def quit_app(*_):
        if quitting.is_set():
            return
        quitting.set()
        engine.shutdown()
        icon.stop()
        window.destroy()

    def on_closing():
        if quitting.is_set():
            return True
        if rgbman_win.shutting_down():  # sign-out/shutdown: refusing would block Windows
            quitting.set()
            engine.shutdown("windows")
            icon.stop()
            return True
        if engine.app["close_to_tray"]:
            window.hide()
        else:  # destroy() from inside the closing handler would deadlock
            threading.Thread(target=quit_app, daemon=True).start()
        return False

    window.events.closing += on_closing

    def power_toggle(icon, item):
        engine.update_settings({"power": not engine.settings["power"]})

    def open_settings(*_):
        show()
        window.evaluate_js("openSettings()")

    def effect_item(eid):
        return pystray.MenuItem(lambda it: tr(rgbman.EFFECTS[eid][0]),
                                lambda i, it: engine.update_settings({"effect": eid, "power": True}),
                                checked=lambda it: engine.settings["effect"] == eid, radio=True)

    def profile_items():
        names = list(engine.profiles())
        if not names:
            return [pystray.MenuItem(tr("Brak profili"), None, enabled=False)]
        return [pystray.MenuItem(n, (lambda n: lambda i, it: engine.apply_profile(n))(n)) for n in names]

    icon = pystray.Icon("rgbman", tray_image(), "rgbman", pystray.Menu(
        pystray.MenuItem(lambda it: tr("Pokaż"), lambda i, it: show(), default=True),
        pystray.MenuItem(lambda it: tr("Światła włączone"), power_toggle,
                         checked=lambda item: engine.settings["power"]),
        pystray.MenuItem(lambda it: tr("Efekt"), pystray.Menu(*[
            pystray.MenuItem((lambda label: lambda it: tr(label))(label), pystray.Menu(*[effect_item(e) for e in effects]))
            for _, label, effects in rgbman.EFFECT_GROUPS])),
        pystray.MenuItem(lambda it: tr("Profil"), pystray.Menu(profile_items)),
        pystray.MenuItem(lambda it: tr("Ustawienia"), open_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda it: tr("Zakończ"), quit_app),
    ))

    def tray_sync():
        """Win32 tray menus are built ahead of time: rebuild when the panel changes things."""
        while True:
            engine.changed.wait()
            engine.changed.clear()
            try:
                icon.title = f"rgbman: {tr(rgbman.EFFECTS[engine.settings['effect']][0])}" + (
                    "" if engine.settings["power"] else tr(" (wyłączone)"))
                icon.update_menu()
            except Exception as e:
                rgbman.log(f"tray: {e}")
            time.sleep(0.3)  # coalesce bursts (e.g. dragging a color)

    threading.Thread(target=icon.run, daemon=True).start()
    engine.changed.set()
    threading.Thread(target=tray_sync, daemon=True).start()
    # the hidden webview window may never be asked to close at shutdown: own hook, notified early
    rgbman_win.on_session_end(lambda: engine.shutdown("windows"))

    def boot():
        engine.rescan(wait=90 if a.hidden else 5)
        threading.Thread(target=engine.run_schedule, daemon=True).start()
        engine.loop()

    threading.Thread(target=boot, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        fatal(traceback.format_exc())
        sys.exit(1)
