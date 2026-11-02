#!/usr/bin/env python3
"""rgbman - local all-in-one RGB manager (Windows 11).

Backends:
  openrgb   ASRock RX 9070 XT, Gigabyte B650 Eagle AX ARGB headers (Lian Li V100 fans + strip),
            and anything else OpenRGB detects
  rivalcfg  SteelSeries Rival 5 (only if OpenRGB doesn't already expose it)
  hid       Maono PD100X (built in), raw HID devices defined in config.json (Akko TAC87) once captured
"""
from __future__ import annotations

import argparse
import colorsys
import json
import math
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.json"
PROFILES_FILE = HERE / "profiles.json"
FPS = 30
# name: (label, uses second color, animated)
EFFECTS = {
    "static": ("Statyczny", False, False),
    "gradient": ("Gradient", True, False),
    "rainbow": ("Tęcza", False, True),
    "cycle": ("Cykl kolorów", False, True),
    "breathe": ("Oddech", False, True),
    "heartbeat": ("Bicie serca", False, True),
    "wave": ("Fala", False, True),
    "flow": ("Przepływ", True, True),
    "aurora": ("Zorza", True, True),
    "comet": ("Kometa", True, True),
    "chase": ("Pościg", True, True),
    "twinkle": ("Iskry", True, True),
    "fire": ("Ogień", False, True),
    "pulse": ("Puls muzyki", True, True),
    "spectrum": ("Spektrum", False, True),
    "vu": ("Wskaźnik VU", True, True),
}
# react to system audio; for these "speed" is the sensitivity
AUDIO_EFFECTS = {"pulse", "spectrum", "vu"}


def log(msg):
    print(f"[rgbman] {msg}", file=sys.stderr)


# ---------------------------------------------------------------- colors
def parse_hex(s: str):
    s = s.strip().lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError(f"bad color '{s}', use RRGGBB")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def hsv(h, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, v)
    return int(r * 255), int(g * 255), int(b * 255)


def scale(c, k):
    return tuple(int(x * k) for x in c)


def mix(a, b, k):
    k = min(max(k, 0.0), 1.0)
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


def _noise(a, b):
    """Deterministic 0..1 hash, so effects need no per-LED state."""
    x = (a * 374761393 + b * 668265263) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 1274126177) & 0xFFFFFFFF
    return (x ^ (x >> 16)) / 0xFFFFFFFF


_FIRE = [(0, 0, 0), (180, 10, 0), (255, 80, 0), (255, 170, 20), (255, 230, 120)]


def _fire_color(k):
    k = min(max(k, 0.0), 0.999) * (len(_FIRE) - 1)
    j = int(k)
    return mix(_FIRE[j], _FIRE[j + 1], k - j)


def frame(effect, t, i, n, color, speed, color2=(0, 0, 0)):
    pos = i / n
    ts = t * speed
    if effect == "gradient":
        return mix(color, color2, i / (n - 1) if n > 1 else 0)
    if effect == "rainbow":
        return hsv(ts * 0.2 + pos)
    if effect == "cycle":
        return hsv(ts * 0.2)
    if effect == "breathe":
        return scale(color, (math.sin(ts * 2) + 1) / 2)
    if effect == "heartbeat":
        p = (ts * 0.8) % 1
        k = max(math.exp(-((p - 0.10) / 0.04) ** 2), 0.7 * math.exp(-((p - 0.28) / 0.04) ** 2))
        return scale(color, 0.08 + 0.92 * k)
    if effect == "wave":
        return scale(color, (math.sin(ts * 3 - 2 * math.pi * pos) + 1) / 2)
    if effect == "flow":
        return mix(color, color2, (math.sin(2 * math.pi * (pos - ts * 0.2)) + 1) / 2)
    if effect == "aurora":
        k = 0.5 + (math.sin(ts * 0.7 + pos * 6) + math.sin(ts * 1.3 - pos * 4)) / 4
        return scale(mix(color, color2, k), 0.55 + 0.45 * math.sin(ts * 0.9 + pos * 9) ** 2)
    if effect == "comet":
        behind = ((ts * 0.5) % 1 - pos) % 1  # distance behind the head
        return mix(color2, color, max(0.0, 1 - behind / 0.25) ** 2)
    if effect == "chase":
        return color if (i + int(ts * 8)) % 3 == 0 else color2
    if effect == "twinkle":
        phase = ts * 3
        bucket = int(phase)
        if _noise(i, bucket) > 0.85:
            return mix(color2, color, math.sin(math.pi * (phase - bucket)))
        return color2
    if effect == "fire":
        k = 0.55 + 0.25 * math.sin(ts * 3 + i * 0.9) + 0.35 * (_noise(i, int(ts * 12)) - 0.5)
        return _fire_color(k * (1 - 0.35 * pos))
    if effect == "pulse":
        return mix(color2, color, AUDIO.read().bass * speed)
    if effect == "spectrum":  # bass at the start of each strip, treble at the end
        b = AUDIO.read().bands
        x = pos * (len(b) - 1)
        j = min(int(x), len(b) - 2)
        k = b[j] + (b[j + 1] - b[j]) * (x - j)
        return hsv(pos * 0.75, min(1.0, k * speed))
    if effect == "vu":  # bar grows from the middle out, color -> color2 towards the ends
        level = min(1.0, AUDIO.read().level * speed)
        if n == 1:
            return mix(color2, color, level)
        dist = abs((i + 0.5) / n - 0.5) * 2
        return mix(color, color2, dist) if dist < level else (0, 0, 0)
    return color


def render(d, effect, t, color, speed, color2=(0, 0, 0), uniform=False):
    """Colors for every LED of a device. Each zone gets the whole effect on its own, so
    single-LED zones (GPU, onboard LED) follow the first LED of every strip instead of
    showing a random slice of one long device-wide strip. uniform: the whole device is
    one LED, for devices whose LED order doesn't follow their shape (e.g. a mouse)."""
    if uniform:
        return [frame(effect, t, 0, 1, color, speed, color2)] * d.led_count
    return [frame(effect, t, i, n, color, speed, color2)
            for n in (d.segments or [d.led_count]) for i in range(n)]


# ---------------------------------------------------------------- audio
class Audio:
    """System audio (loopback of the default Windows output) as smoothed 0..1 levels.

    Capture starts on the first read() and the device is released after IDLE seconds
    without readers, so non-audio effects cost nothing."""
    BANDS, RATE, BLOCK, FFT = 16, 48000, 1024, 4096
    IDLE, FLOOR = 3.0, 1e-4

    def __init__(self):
        self.bands, self.level, self.bass = [0.0] * self.BANDS, 0.0, 0.0
        self.error = None
        self._used = 0.0
        self._wake = threading.Event()
        self._thread = None

    def read(self):
        self._used = time.monotonic()
        if not self._wake.is_set():
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
            self._wake.set()
        return self

    def _run(self):
        # soundcard initializes COM for the importing thread, so import it here, not globally
        try:
            import numpy as np
            import soundcard as sc
        except ImportError:
            self.error = "brak biblioteki: pip install soundcard numpy"
            log(self.error)
            return
        except Exception as e:
            self.error = f"audio: {e}"
            log(self.error)
            return
        warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)

        df = self.RATE / self.FFT
        edges = np.geomspace(40, 16000, self.BANDS + 1)
        bins = []
        for lo, hi in zip(edges, edges[1:]):
            a = max(1, round(lo / df))
            bins.append((a, max(a + 1, round(hi / df))))
        window = np.hanning(self.FFT)
        norm = 2 / window.sum()
        delay = 1  # retry backoff after a capture error, doubles up to 30 s

        while True:
            self._wake.wait()
            buf = np.zeros(self.FFT)
            peak, smooth = np.full(self.BANDS, self.FLOOR), np.zeros(self.BANDS)
            level_peak, level = self.FLOOR, 0.0
            try:
                speaker = sc.default_speaker()
                mic = sc.get_microphone(speaker.id, include_loopback=True)
                checked = time.monotonic()
                with mic.recorder(samplerate=self.RATE, blocksize=self.BLOCK) as rec:
                    self.error = None
                    while time.monotonic() - self._used < self.IDLE:
                        x = rec.record(numframes=self.BLOCK).mean(axis=1)
                        buf = np.concatenate((buf[len(x):], x))

                        mag = np.abs(np.fft.rfft(buf * window)) * norm
                        v = np.array([np.sqrt(np.mean(mag[a:b] ** 2)) for a, b in bins])
                        # per-band auto gain, but never louder than 5% of the loudest band,
                        # so quiet bands don't blow noise up to full brightness
                        peak = np.maximum.reduce([peak * 0.997, v, np.full_like(v, max(peak.max() * 0.05, self.FLOOR))])
                        k = np.clip(v / peak, 0, 1)
                        smooth = np.where(k > smooth, k, smooth * 0.8 + k * 0.2)  # fast attack, soft release

                        rms = float(np.sqrt(np.mean(x ** 2)))
                        level_peak = max(level_peak * 0.997, rms, self.FLOOR)
                        k = rms / level_peak
                        level = k if k > level else level * 0.85 + k * 0.15

                        self.bands, self.level = smooth.tolist(), level
                        self.bass = float(smooth[:4].max())
                        if time.monotonic() - checked > 3:  # follow switching speakers/headphones
                            checked = time.monotonic()
                            if sc.default_speaker().id != speaker.id:
                                break
            except Exception as e:
                if f"audio: {e}" != self.error:  # log each distinct problem once
                    self.error = f"audio: {e}"
                    log(self.error)
                delay = min(delay * 2, 30)
                time.sleep(delay)
            else:
                delay = 1
            self.bands, self.level, self.bass = [0.0] * self.BANDS, 0.0, 0.0
            if time.monotonic() - self._used >= self.IDLE:
                self._wake.clear()


AUDIO = Audio()


# ---------------------------------------------------------------- devices
class Device:
    name, backend, led_count, max_fps = "?", "?", 1, FPS
    segments = None  # LED count of each zone, in LED order; None = one zone
    resizable = ()   # zones whose LED count the user sets: [{name, size, min, max}]

    def prepare(self):
        pass

    def set_leds(self, colors):
        raise NotImplementedError

    def close(self):
        pass


class OpenRGBDevice(Device):
    # OpenRGB coalesces SDK updates per controller, so the app's fps setting decides;
    # slow controllers (I2C GPUs) can be capped per device in the panel
    backend, max_fps = "openrgb", 60

    def __init__(self, dev):
        self.dev, self.name = dev, dev.name
        self.led_count = max(len(dev.leds), 1)
        zones = [len(z.leds) for z in dev.zones if z.leds]
        if sum(zones) == len(dev.leds) > 0:
            self.segments = zones
        # ARGB headers: OpenRGB can't know what is plugged in, the size is set by the user
        self.resizable = [{"name": z.name, "size": len(z.leds), "min": z.leds_min, "max": z.leds_max}
                          for z in dev.zones if getattr(z, "leds_min", 0) != getattr(z, "leds_max", 0)]
        self.mode = None

    def prepare(self):
        for mode in ("direct", "static", "custom"):
            try:
                self.dev.set_mode(mode)
                self.mode = mode
                return
            except Exception:
                continue

    def set_leds(self, colors):
        from openrgb.utils import RGBColor
        if not self.dev.leds:
            return
        if self.mode == "direct":
            self.dev.set_colors([RGBColor(*c) for c in colors], fast=True)
        else:  # static-only device: one color
            self.dev.set_color(RGBColor(*colors[0]), fast=True)

    def close(self):
        try:
            self.client.disconnect()
        except Exception:
            pass


class RivalDevice(Device):
    backend, max_fps = "rivalcfg", 10  # each zone is a separate HID write

    def __init__(self, mouse):
        self.mouse = mouse
        profile = mouse.mouse_profile
        self.name = profile.get("name", "SteelSeries mouse")
        self.setters = [
            getattr(mouse, f"set_{key}")
            for key, s in profile["settings"].items()
            if "color" in key and "reactive" not in key and "rgb" in s.get("value_type", "")
        ]
        self.led_count = max(len(self.setters), 1)

    def set_leds(self, colors):
        for setter, c in zip(self.setters, colors):
            setter("#%02x%02x%02x" % c)


class HidDevice(Device):
    """Uniform-color device driven by packet templates captured from the vendor app."""
    backend = "hid"

    def __init__(self, spec, path):
        import hid
        self.spec, self.name = spec, spec["name"]
        self.max_fps = spec.get("max_fps", 0)  # 0 = static only
        self.h = hid.device()
        self.h.open_path(path)

    def set_leds(self, colors):
        r, g, b = colors[0]
        for tpl in self.spec["packets"]:
            data = bytes.fromhex(tpl.format(r=f"{r:02x}", g=f"{g:02x}", b=f"{b:02x}"))
            if self.spec.get("method", "write") == "feature":
                self.h.send_feature_report(data)
            else:
                self.h.write(data)
        time.sleep(self.spec.get("delay_ms", 0) / 1000)

    def close(self):
        self.h.close()


class MaonoDevice(Device):
    """Maono PD100X microphone. Protocol captured from Maono Link 3 (Maono Link2.0.exe):
    output report 0x4B, `c4 0b 00 00 03 <param> 20 <u16 value LE> <u16 checksum LE>`,
    padded to 64 bytes; checksum = 0x10000 - sum of the 9 bytes before it.

    The ring can't show arbitrary RGB, only 8 palette colors (+ the mic's own color
    cycle), at 0-100 % brightness: each frame is mapped to the nearest palette hue.

    Every write blocks ~16 ms (the endpoint's polling interval, measured: ~62 writes/s),
    and a frame is 1-3 writes, so frames go out from a writer thread: set_leds() only hands over the
    newest frame and never stalls the render loop that drives the other devices."""
    backend, max_fps = "hid", 15  # divides 30 and 60, so frames stay evenly spaced
    VID, PID = 0x352F, 0x010C
    LIGHT, COLOR, BRIGHTNESS, MODE = 0x36, 0x38, 0x37, 0x39  # also 0x22: off while muted
    # palette index -> hue in degrees; 0 is the mic's built-in rainbow, 8 is white
    HUES = {1: 0, 2: 30, 3: 60, 4: 120, 5: 180, 6: 240, 7: 280}
    WHITE = 8

    def __init__(self, path):
        import hid
        self.name = "Maono PD100X"
        self.h = hid.device()
        self.h.open_path(path)
        self.sent = {}  # param -> last value, so steady frames cost no USB traffic
        self._frame, self._error, self._closed = None, None, False
        self._wake, self._idle = threading.Event(), threading.Event()
        self._idle.set()
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._thread.start()

    def _send(self, param, value):
        if self.sent.get(param) == value:
            return
        body = bytes([0xC4, 0x0B, 0x00, 0x00, 0x03, param, 0x20, value & 0xFF, value >> 8])
        check = (0x10000 - sum(body)) & 0xFFFF
        self.h.write((b"\x4b" + body + check.to_bytes(2, "little")).ljust(64, b"\0"))
        self.sent[param] = value

    def prepare(self):
        self.sent.clear()
        self._send(self.MODE, 0)  # static: rgbman does the animating

    @classmethod
    def palette_index(cls, c):
        hi, lo = max(c), min(c)
        if hi - lo < 0.25 * hi:
            return cls.WHITE
        h = colorsys.rgb_to_hsv(*(x / 255 for x in c))[0] * 360
        return min(cls.HUES, key=lambda k: min(abs(h - cls.HUES[k]), 360 - abs(h - cls.HUES[k])))

    def _apply(self, c):
        level = round(max(c) / 255 * 100)
        self._send(self.LIGHT, int(level > 0))
        if level:
            self._send(self.COLOR, self.palette_index(c))
            self._send(self.BRIGHTNESS, level)

    def _writer(self):
        while not self._closed:
            self._wake.wait()
            self._wake.clear()  # a frame arriving from here on wakes us again
            if self._frame is not None and not self._closed:
                try:
                    self._apply(self._frame)
                except Exception as e:
                    self._error = e
            if not self._wake.is_set():
                self._idle.set()

    def set_leds(self, colors):
        if self._error:  # report write failures to the caller, like the other devices
            e, self._error = self._error, None
            raise e
        self._idle.clear()
        self._frame = colors[0]  # newest wins: frames the USB can't keep up with are dropped
        self._wake.set()

    def close(self):
        self._idle.wait(0.5)  # let the last frame (e.g. lights off on exit) go out
        self._closed = True
        self._wake.set()
        self._thread.join(0.5)
        self.h.close()


def find_maono():
    import hid
    for d in hid.enumerate(MaonoDevice.VID, MaonoDevice.PID):
        if d["usage_page"] == 0x000C:  # the consumer-control collection carries report 0x4B
            return d["path"]
    return None


def find_hid_path(spec):
    import hid
    for d in hid.enumerate(int(spec["vid"], 16), int(spec["pid"], 16)):
        if "usage_page" in spec and d["usage_page"] != int(spec["usage_page"], 16):
            continue
        if "interface" in spec and d["interface_number"] != spec["interface"]:
            continue
        return d["path"]
    return None


def _keep_zone_limits():
    """openrgb-python drops a zone's min/max LED count; keep them to tell resizable zones apart."""
    from openrgb.orgb import Zone
    if getattr(Zone, "_rgbman_limits", False):
        return
    update = Zone._update

    def _update(self, data):
        update(self, data)
        self.leds_min, self.leds_max = data.leds_min, data.leds_max

    Zone._update, Zone._rgbman_limits = _update, True


def _settle(client, limit=30, quiet=4):
    """A freshly started OpenRGB answers before it has found all controllers (I2C ones take
    seconds). Poll until the device list stays the same for `quiet` seconds."""
    end, prev, since = time.monotonic() + limit, None, time.monotonic()
    while time.monotonic() < end:
        sig = (len(client.devices), sum(len(d.leds) for d in client.devices))
        if sig != prev:
            prev, since = sig, time.monotonic()
        elif sig[0] and time.monotonic() - since >= quiet:
            return
        time.sleep(1)
        client.update()


def _apply_zone_sizes(client, sizes):
    """OpenRGB forgets SDK resizes on restart, so re-apply real ARGB sizes every scan."""
    resized = False
    for d in client.devices:
        for z in d.zones:
            want = sizes.get(d.name, {}).get(z.name)
            if not isinstance(want, int) or isinstance(want, bool) or len(z.leds) == want:
                continue
            try:
                z.resize(want)
                resized = True
            except Exception as e:
                log(f"resize {d.name}/{z.name} -> {want}: {e}")
    if resized:
        client.update()


def discover(cfg, wait=0, settle=False):
    deadline = time.monotonic() + wait
    devices = []
    oc = cfg.get("openrgb", {})
    while True:
        try:
            from openrgb import OpenRGBClient
        except ImportError:
            log("openrgb-python missing: pip install openrgb-python")
            break
        _keep_zone_limits()
        try:
            client = OpenRGBClient(oc.get("host", "127.0.0.1"), oc.get("port", 6742), "rgbman")
        except Exception:
            if time.monotonic() >= deadline:
                log("OpenRGB SDK server not reachable - start OpenRGB with --server")
                break
            settle = True  # server wasn't up yet: it is starting now
            time.sleep(2)
            continue
        try:
            if settle:
                _settle(client)
            _apply_zone_sizes(client, oc.get("zone_sizes", {}))
            for d in client.devices:
                dev = OpenRGBDevice(d)
                dev.client = client
                devices.append(dev)
        except Exception as e:
            log(f"OpenRGB: {e}")
            devices = []
            try:
                client.disconnect()
            except Exception:
                pass
        break

    if cfg.get("rivalcfg", True) and not any("rival" in d.name.lower() for d in devices):
        try:
            import rivalcfg
            mouse = rivalcfg.get_first_mouse()
            if mouse:
                devices.append(RivalDevice(mouse))
        except ImportError:
            pass
        except Exception as e:
            log(f"rivalcfg: {e}")

    if cfg.get("maono", True):
        try:
            path = find_maono()
            if path:
                devices.append(MaonoDevice(path))
        except ImportError:
            log("hidapi missing: pip install hidapi")
        except Exception as e:
            log(f"Maono PD100X: {e}")

    for spec in cfg.get("hid", []):
        if not spec.get("enabled") or not spec.get("packets"):
            continue
        try:
            path = find_hid_path(spec)
            if path:
                devices.append(HidDevice(spec, path))
            else:
                log(f"{spec['name']}: not found")
        except Exception as e:
            log(f"{spec['name']}: {e}")
    return devices


def select(devices, filters):
    if not filters:
        return devices
    out = []
    for f in filters:
        for i, d in enumerate(devices):
            if (f.isdigit() and int(f) == i) or f.lower() in d.name.lower():
                if d not in out:
                    out.append(d)
    return out


# ---------------------------------------------------------------- engine
def run(devices, effect, color, speed, color2=(0, 0, 0)):
    animated_fx = EFFECTS[effect][2]
    alive = []
    for d in devices:
        try:
            d.prepare()
            if d.max_fps > 0:
                d.set_leds(render(d, effect, 0, color, speed, color2))
            else:  # static-only device: plain main color, like the app
                d.set_leds([color] * d.led_count)
            alive.append(d)
        except Exception as e:
            log(f"{d.name}: {e}")
    if not animated_fx:
        return

    animated = [d for d in alive if d.max_fps > 0]
    last = {id(d): 0.0 for d in animated}
    t0 = time.monotonic()
    log(f"running '{effect}' on {len(animated)} device(s), Ctrl+C to stop")
    try:
        while animated:
            now = time.monotonic()
            for d in list(animated):
                if now - last[id(d)] < 1 / d.max_fps:
                    continue
                last[id(d)] = now
                try:
                    d.set_leds(render(d, effect, now - t0, color, speed, color2))
                except Exception as e:
                    log(f"{d.name}: {e} - dropped")
                    animated.remove(d)
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------- cli
def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def cmd_list(cfg, a):
    for i, d in enumerate(discover(cfg)):
        print(f"{i:2}  [{d.backend:8}] {d.name}  leds={d.led_count}  max_fps={d.max_fps}")


def cmd_hid_scan(cfg, a):
    import hid
    for d in sorted(hid.enumerate(), key=lambda x: (x["vendor_id"], x["product_id"])):
        print(f"{d['vendor_id']:04x}:{d['product_id']:04x}  page=0x{d['usage_page']:04x} "
              f"usage=0x{d['usage']:04x} if={d['interface_number']:2}  "
              f"{d['manufacturer_string']} {d['product_string']}")


def cmd_set(cfg, a):
    devs = select(discover(cfg, a.wait), a.device)
    if not devs:
        sys.exit("no matching devices")
    run(devs, a.effect, a.color, a.speed, a.color2)


def cmd_save(cfg, a):
    profiles = load_json(PROFILES_FILE, {})
    profiles[a.name] = {"effect": a.effect, "color": "%02x%02x%02x" % a.color,
                        "color2": "%02x%02x%02x" % a.color2, "speed": a.speed, "device": a.device}
    PROFILES_FILE.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    print(f"saved '{a.name}'")


def cmd_apply(cfg, a):
    profiles = load_json(PROFILES_FILE, {})
    if a.name not in profiles:
        sys.exit(f"unknown profile '{a.name}', have: {', '.join(profiles) or 'none'}")
    p = profiles[a.name]
    devs = select(discover(cfg, a.wait), p.get("device"))
    color = scale(parse_hex(p["color"]), p.get("brightness", 1.0))
    color2 = scale(parse_hex(p.get("color2", "000000")), p.get("brightness", 1.0))
    run(devs, p["effect"], color, p["speed"], color2)


def cmd_profiles(cfg, a):
    for name, p in load_json(PROFILES_FILE, {}).items():
        print(f"{name}: {p}")


def cmd_autostart(cfg, a):
    if a.remove:
        subprocess.run(["schtasks", "/Delete", "/TN", "rgbman", "/F"], check=False)
        return
    pyw = Path(sys.executable).with_name("pythonw.exe")
    tr = f'"{pyw}" "{Path(__file__).resolve()}" apply {a.name} --wait 90'
    subprocess.run(["schtasks", "/Create", "/TN", "rgbman", "/SC", "ONLOGON",
                    "/RL", "HIGHEST", "/TR", tr, "/F"], check=True)
    print(f"profile '{a.name}' will apply at logon")


def main():
    ap = argparse.ArgumentParser(prog="rgbman", description="Local all-in-one RGB manager")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def effect_args(p, positional_effect=True):
        if positional_effect:
            p.add_argument("effect", choices=list(EFFECTS))
        else:
            p.add_argument("--effect", choices=list(EFFECTS), default="static")
        p.add_argument("-c", "--color", type=parse_hex, default=parse_hex("00b4ff"))
        p.add_argument("-c2", "--color2", type=parse_hex, default=parse_hex("000000"),
                       help="second color (gradient, flow, aurora, comet, chase, twinkle, pulse, vu)")
        p.add_argument("-s", "--speed", type=float, default=1.0,
                       help="speed; sensitivity for pulse, spectrum, vu")
        p.add_argument("-d", "--device", action="append", help="index or name substring (repeatable)")

    sub.add_parser("list", help="list controllable devices").set_defaults(fn=cmd_list)
    sub.add_parser("hid-scan", help="list raw HID interfaces (for vid/pid lookup)").set_defaults(fn=cmd_hid_scan)

    p = sub.add_parser("set", help="apply an effect now")
    effect_args(p)
    p.add_argument("--wait", type=int, default=0, help="seconds to wait for OpenRGB")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("off", help="turn everything off")
    p.add_argument("-d", "--device", action="append")
    p.set_defaults(fn=lambda cfg, a: run(select(discover(cfg), a.device), "static", (0, 0, 0), 1))

    p = sub.add_parser("save", help="save a profile")
    p.add_argument("name")
    effect_args(p, positional_effect=False)
    p.set_defaults(fn=cmd_save)

    p = sub.add_parser("apply", help="apply a saved profile")
    p.add_argument("name")
    p.add_argument("--wait", type=int, default=0)
    p.set_defaults(fn=cmd_apply)

    sub.add_parser("profiles", help="list saved profiles").set_defaults(fn=cmd_profiles)

    p = sub.add_parser("autostart", help="apply a profile at Windows logon (run as admin)")
    p.add_argument("name", nargs="?", default="default")
    p.add_argument("--remove", action="store_true")
    p.set_defaults(fn=cmd_autostart)

    a = ap.parse_args()
    a.fn(load_json(CONFIG_FILE, {}), a)


if __name__ == "__main__":
    main()
