import ctypes
import json
import logging
import os
import random
import sys
import threading
import time
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import customtkinter as ctk
import win32api
import win32event
import win32gui
import winerror
from PIL import Image, ImageDraw

try:
    import keyboard
    _KEYBOARD_OK = True
except Exception:
    keyboard = None
    _KEYBOARD_OK = False


# ── Win32 key input: SendInput with virtual key + scan code ──

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_MAPVK_VK_TO_VSC = 0

_VkKeyScanA = ctypes.windll.user32.VkKeyScanA
_VkKeyScanA.restype = ctypes.c_short
_VkKeyScanA.argtypes = [ctypes.c_wchar]

_SendInput = ctypes.windll.user32.SendInput
_SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
_SendInput.restype = ctypes.c_uint

_GetLastError = ctypes.windll.kernel32.GetLastError
_GetLastError.restype = wintypes.DWORD

_MapVirtualKeyW = ctypes.windll.user32.MapVirtualKeyW
_MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
_MapVirtualKeyW.restype = ctypes.c_uint


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUT_UNION)]


def _send_key(char, down=True):
    vk = _VkKeyScanA(char) & 0xFF
    scan = _MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC)
    flags = 0 if down else _KEYEVENTF_KEYUP
    inp = _INPUT()
    inp.type = _INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = scan
    inp.ki.dwFlags = flags
    n = _SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
    err = _GetLastError() if n == 0 else 0
    return n, err


_MODIFIER_NAMES = {
    "shift", "left shift", "right shift",
    "ctrl", "left ctrl", "right ctrl",
    "alt", "left alt", "right alt", "alt gr",
    "windows", "left windows", "right windows",
    "caps lock", "num lock", "scroll lock", "menu",
}


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("bongoclicker")


CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".bongoclicker.json")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, "cat.ico")
LOG_PATH = os.path.join(SCRIPT_DIR, "bongoclicker.log")

_fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
log.addHandler(_fh)

MUTEX_NAME = "Global\\BongoCatClickerSingleInstance"

BONGO_TITLES = ["BongoCat", "Bongo Cat"]
EXCLUDE_TITLES = ["clicker", "bot"]
SPAM_CHARS = list("abcdefghijklmnopqrstuvwxyz0123456789")
HOLD_MIN = 0.035
HOLD_MAX = 0.055

SPEED_PRESETS = {
    "slow": (0.06, 0.09, 0.035, 0.055),
    "medium": (0.025, 0.04, 0.035, 0.055),
    "fast": (0.001, 0.003, 0.020, 0.030),
    "custom": (0.001, 0.003, 0.020, 0.030),
}

DEFAULT_CONFIG = {
    "hotkey": "f6",
    "theme": "dark",
    "speed": "medium",
    "custom_min": 0.025,
    "custom_max": 0.04,
}

DEPRECATED_KEYS = {"auto_chest", "chest_interval", "auto_start"}

DARK = {
    "bg": "#1A1612",
    "card": "#2A2218",
    "card_border": "#3D3225",
    "accent": "#D97706",
    "accent_hover": "#B45309",
    "green": "#34D399",
    "red": "#F87171",
    "red_hover": "#EF4444",
    "orange": "#FBBF24",
    "text": "#F5EDE4",
    "text_sec": "#A89882",
    "text_dim": "#6B5D4F",
    "divider": "#3D3225",
}
LIGHT = {
    "bg": "#F5F0E8",
    "card": "#FFFFFF",
    "card_border": "#C4B59A",
    "accent": "#C2610A",
    "accent_hover": "#9A4D08",
    "green": "#16A34A",
    "red": "#DC2626",
    "red_hover": "#B91C1C",
    "orange": "#D97706",
    "text": "#2C1A05",
    "text_sec": "#6B5234",
    "text_dim": "#9A8668",
    "divider": "#C4B59A",
}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    dirty = False
    for k in DEPRECATED_KEYS:
        if k in cfg:
            del cfg[k]
            dirty = True
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    if dirty:
        save_config(cfg)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def _is_patched():
    base = _find_game_dir()
    if not base:
        return False
    dll = os.path.join(base, "BongoCat_Data", "Managed", "Assembly-CSharp.dll")
    if not os.path.exists(dll):
        return False
    try:
        with open(dll, "rb") as f:
            data = f.read()
        return b"AutoClaimV3" in data
    except Exception:
        return False


def _find_game_dir():
    candidates = [
        r"C:\Program Files (x86)\Steam\steamapps\common\BongoCat",
    ]
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Valve\Steam",
        ) as key:
            steam_path = winreg.QueryValueEx(key, "InstallPath")[0]
        candidates.append(os.path.join(steam_path, "steamapps", "common", "BongoCat"))
    except Exception:
        pass
    for p in candidates:
        if os.path.exists(os.path.join(p, "BongoCat.exe")):
            return p
    return None


_bongo_hwnd_cache = {"hwnd": None, "ts": 0}
_bongo_cache_lock = threading.Lock()
_BONGO_CACHE_TTL = 1.0


def find_bongo():
    now = time.time()
    with _bongo_cache_lock:
        cached = _bongo_hwnd_cache
        if cached["hwnd"] and (now - cached["ts"]) < _BONGO_CACHE_TTL:
            hwnd = cached["hwnd"]
            if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                return hwnd
        results = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            t = win32gui.GetWindowText(hwnd).lower()
            for ex in EXCLUDE_TITLES:
                if ex in t:
                    return
            for bt in BONGO_TITLES:
                if bt.lower() in t:
                    results.append(hwnd)
                    return

        try:
            win32gui.EnumWindows(cb, None)
        except Exception:
            pass
        _bongo_hwnd_cache["hwnd"] = results[0] if results else None
        _bongo_hwnd_cache["ts"] = now
        return _bongo_hwnd_cache["hwnd"]


def create_app_icon(path):
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, s - 2, s - 2], radius=52, fill="#B45309")
    ov = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for i in range(s // 2):
        od.line(
            [(4, i + 4), (s - 4, i + 4)],
            fill=(255, 255, 255, int(50 * (1 - i / (s // 2)))),
        )
    img = Image.alpha_composite(img, ov)
    d = ImageDraw.Draw(img)
    cx, cy = s // 2, s // 2 + 18
    d.ellipse(
        [cx - 72, cy - 72, cx + 72, cy + 72], fill="#FF9800", outline="#E65100", width=2
    )
    d.polygon(
        [(cx - 60, cy - 64), (cx - 62, cy - 118), (cx - 12, cy - 68)],
        fill="#FF9800",
        outline="#E65100",
        width=2,
    )
    d.polygon(
        [
            (p[0] + 8, p[1] + 10)
            for p in [(cx - 60, cy - 64), (cx - 62, cy - 118), (cx - 12, cy - 68)]
        ],
        fill="#FFB74D",
    )
    d.polygon(
        [(cx + 60, cy - 64), (cx + 62, cy - 118), (cx + 12, cy - 68)],
        fill="#FF9800",
        outline="#E65100",
        width=2,
    )
    d.polygon(
        [
            (p[0] - 8, p[1] + 10)
            for p in [(cx + 60, cy - 64), (cx + 62, cy - 118), (cx + 12, cy - 68)]
        ],
        fill="#FFB74D",
    )
    d.ellipse([cx - 43, cy - 25, cx - 9, cy + 9], fill="white")
    d.ellipse([cx + 9, cy - 25, cx + 43, cy + 9], fill="white")
    d.ellipse([cx - 24, cy - 13, cx - 6, cy + 5], fill="#1E1B2E")
    d.ellipse([cx + 6, cy - 13, cx + 24, cy + 5], fill="#1E1B2E")
    d.ellipse([cx - 20, cy - 10, cx - 10, cy], fill="white")
    d.ellipse([cx + 10, cy - 10, cx + 20, cy], fill="white")
    d.polygon([(cx - 6, cy + 18), (cx + 6, cy + 18), (cx, cy + 28)], fill="#F472B6")
    d.arc([cx - 16, cy + 24, cx, cy + 42], 10, 170, fill="#5D4037", width=2)
    d.arc([cx, cy + 24, cx + 16, cy + 42], 10, 170, fill="#5D4037", width=2)
    img.save(
        path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def create_tray_icon_image():
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, s - 2, s - 2], radius=14, fill="#D97706")
    cx, cy = 32, 36
    d.ellipse([cx - 18, cy - 18, cx + 18, cy + 18], fill="#FF9800")
    d.ellipse([cx - 8, cy - 6, cx - 2, cy], fill="white")
    d.ellipse([cx + 2, cy - 6, cx + 8, cy], fill="white")
    d.polygon([(cx - 2, cy + 4), (cx + 2, cy + 4), (cx, cy + 8)], fill="#F472B6")
    return img


class Engine:
    def __init__(self, stats_cb, cfg_ref):
        self.running = False
        self._alive = True
        self.lock = threading.Lock()
        self._stats_cb = stats_cb
        self._cfg_ref = cfg_ref
        self.total = 0
        self.cps = 0.0
        self._wc = 0
        self._ws = time.time()
        self._wake = threading.Event()
        self.diag = "starte..."
        self._last_err = 0
        log.info("Engine-Thread gestartet")
        threading.Thread(target=self._loop, daemon=True).start()

    def start(self):
        with self.lock:
            self.running = True
        self._wake.set()

    def stop(self):
        with self.lock:
            self.running = False
        self._wake.set()

    def kill(self):
        self._alive = False
        self._wake.set()

    def reset(self):
        with self.lock:
            self.total = 0
            self.cps = 0.0
            self._wc = 0
            self._ws = time.time()

    def _get_intervals(self):
        cfg = self._cfg_ref()
        p = cfg.get("speed", "medium")
        if p == "custom":
            return (
                cfg.get("custom_min", 0.025),
                cfg.get("custom_max", 0.04),
                HOLD_MIN,
                HOLD_MAX,
            )
        return SPEED_PRESETS.get(p, SPEED_PRESETS["medium"])

    def _loop(self):
        while self._alive:
            with self.lock:
                r = self.running
            if not r:
                self._wake.wait(0.2)
                self._wake.clear()
                self.diag = "gestoppt"
                continue
            hwnd = find_bongo()
            if not hwnd:
                self.diag = "kein BongoCat-Fenster gefunden - Spiel offen?"
                time.sleep(0.5)
                continue
            imin, imax, hmin, hmax = self._get_intervals()
            k = "?"
            sent_ok = False
            try:
                k = random.choice(SPAM_CHARS)
                n1, e1 = _send_key(k, True)
                time.sleep(random.uniform(hmin, hmax))
                n2, e2 = _send_key(k, False)
                sent_ok = bool(n1 and n2)
                self._last_err = e1 or e2
                with self.lock:
                    self.total += 1
                    self._wc += 1
            except Exception as e:
                log.warning("Key input failed: %s", e)
                self._last_err = -1
            if sent_ok:
                self.diag = (
                    f"hwnd 0x{hwnd:x} | tippe '{k}' | SendInput=ok | "
                    f"patched={'ja' if _is_patched() else 'nein'}"
                )
            else:
                self.diag = f"SendInput FEHLGESCHLAGEN (err={self._last_err})"
            now = time.time()
            with self.lock:
                elapsed = now - self._ws
                if elapsed >= 0.4:
                    self.cps = self._wc / elapsed
                    self._wc = 0
                    self._ws = now
                    if self._stats_cb:
                        try:
                            self._stats_cb(self.cps, self.total)
                        except Exception:
                            pass
            time.sleep(random.uniform(imin, imax))


class CpsGraph(ctk.CTkCanvas):
    def __init__(self, parent, width=380, height=60, **kw):
        super().__init__(parent, width=width, height=height, **kw)
        self._data = []
        self._max_points = 50
        self.configure(highlightthickness=0)

    def add_point(self, cps):
        self._data.append(cps)
        if len(self._data) > self._max_points:
            self._data.pop(0)
        self.redraw()

    def redraw(self):
        self.delete("all")
        if len(self._data) < 2:
            return
        w = int(self.cget("width"))
        h = int(self.cget("height"))
        is_dark = ctk.get_appearance_mode() == "Dark"
        line_color = "#D97706" if is_dark else "#C2610A"
        fill_color = "#2A2218" if is_dark else "#F5F0E8"
        bg_color = "#1A1612" if is_dark else "#FFFFFF"
        self.configure(bg=bg_color)

        max_val = max(self._data) if self._data else 1
        if max_val < 1:
            max_val = 1

        points = []
        for i, v in enumerate(self._data):
            x = (i / (self._max_points - 1)) * w
            y = h - (v / max_val) * (h - 4) - 2
            points.append((x, y))

        fill_pts = [(0, h)] + points + [(w, h)]
        flat_fill = [coord for pt in fill_pts for coord in pt]
        self.create_polygon(flat_fill, fill=fill_color, outline="")

        flat_line = [coord for pt in points for coord in pt]
        if len(flat_line) >= 4:
            self.create_line(flat_line, fill=line_color, width=2, smooth=True)

    def reset_data(self):
        self._data.clear()
        self.delete("all")


class App(ctk.CTk):
    W, PX = 420, 20

    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.engine = None
        self._hk_handle = None
        self._hk_cap_handle = None
        self._hk_cap_timer = None
        self._hk_resume = False
        self.listening = False
        self._alive = True
        self._tray_icon = None
        self._cps_data = []
        self._rebuilding = False
        self._diag_id = None

        ctk.set_appearance_mode(self.cfg.get("theme", "dark"))
        ctk.set_default_color_theme("blue")

        if not os.path.exists(ICON_PATH):
            try:
                create_app_icon(ICON_PATH)
            except Exception:
                pass
        if os.path.exists(ICON_PATH):
            try:
                self.iconbitmap(ICON_PATH)
            except Exception:
                pass

        self.title("Bongo Cat Clicker")
        self.geometry("420x500")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        self._fit_height()
        self._reg_hotkey()
        self._diag_poll()

        self.bind("<<ShowFromTray>>", lambda e: self._show_window())
        self.bind("<<QuitFromTray>>", lambda e: self._on_quit_from_tray())

    def _fit_height(self):
        self.update_idletasks()
        self.geometry(f"420x{self.winfo_reqheight()}")

    def _c(self):
        return DARK if self.cfg.get("theme", "dark") == "dark" else LIGHT

    def _lbl(self, parent, text, size=12, weight="normal", color_key="text_sec", **kw):
        return ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(family="Segoe UI", size=size, weight=weight),
            text_color=self._c()[color_key],
            **kw,
        )

    def _btn(self, parent, text, cmd, w=100, h=30, accent=False, danger=False, **kw):
        c = self._c()
        if accent:
            fg, hv = c["accent"], c["accent_hover"]
        elif danger:
            fg, hv = c["card"], c["red"]
        else:
            fg, hv = c["card"], c["card_border"]
        return ctk.CTkButton(
            parent,
            text=text,
            command=cmd,
            width=w,
            height=h,
            font=ctk.CTkFont(
                family="Segoe UI", size=11, weight="bold" if accent else "normal"
            ),
            fg_color=fg,
            hover_color=hv,
            text_color=c["text"] if accent else c["text_sec"],
            corner_radius=8,
            **kw,
        )

    def _divider(self, parent):
        ctk.CTkFrame(parent, height=1, fg_color=self._c()["divider"]).pack(
            fill="x", padx=self.PX, pady=8
        )

    def _build(self):
        c = self._c()
        self.configure(fg_color=c["bg"])
        for w in self.winfo_children():
            w.destroy()

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=self.PX, pady=(12, 0))
        ctk.CTkLabel(
            row,
            text="Bongo Cat Clicker",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=c["text"],
        ).pack(side="left")
        btn_row = ctk.CTkFrame(row, fg_color="transparent")
        btn_row.pack(side="right")
        self._btn(btn_row, "_", self._on_minimize_to_tray, w=34, h=34).pack(
            side="left", padx=(0, 4)
        )
        self._btn(
            btn_row,
            "\u2600\ufe0f" if c == DARK else "\U0001f319",
            self._toggle_theme,
            w=34,
            h=34,
        ).pack(side="right")

        card = ctk.CTkFrame(
            self,
            fg_color=c["card"],
            corner_radius=12,
            border_width=1,
            border_color=c["card_border"],
        )
        card.pack(fill="x", padx=self.PX, pady=(10, 0))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=10)
        left = ctk.CTkFrame(inner, fg_color="transparent")
        left.pack(side="left")
        self.lbl_status = ctk.CTkLabel(
            left,
            text="\u25cf Stopped",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=c["red"],
        )
        self.lbl_status.pack(anchor="w")
        self.lbl_cps = ctk.CTkLabel(
            left,
            text="0 CPS",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=c["text"],
        )
        self.lbl_cps.pack(anchor="w")

        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="right")
        self.lbl_total = ctk.CTkLabel(
            right,
            text="0",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=c["text"],
        )
        self.lbl_total.pack()
        self._lbl(right, "total", size=10, color_key="text_dim").pack()
        self._btn(right, "Reset", self._reset_total, w=60, h=22).pack(pady=(4, 0))
        if _is_patched():
            self._lbl(right, "Chest: On", size=9, color_key="green").pack(pady=(4, 0))
        else:
            self._lbl(right, "Chest: Unpatched!", size=9, color_key="red").pack(
                pady=(4, 0)
            )

        self._divider(self)

        self.cps_graph = CpsGraph(self, width=380, height=50, bg=c["bg"])
        self.cps_graph.pack(padx=self.PX, pady=(0, 0))
        saved = self._cps_data[:]
        self._cps_data.clear()
        for pt in saved:
            self.cps_graph.add_point(pt)

        self._divider(self)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=self.PX)

        left_s = ctk.CTkFrame(row, fg_color="transparent")
        left_s.pack(side="left", expand=True, fill="x")
        self._lbl(left_s, "SPEED", size=10, weight="bold", color_key="text_dim").pack(
            anchor="w"
        )
        self.speed_var = ctk.StringVar(value=self.cfg.get("speed", "medium"))
        seg = ctk.CTkSegmentedButton(
            left_s,
            values=["slow", "medium", "fast", "custom"],
            variable=self.speed_var,
            command=self._on_speed_change,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            selected_color=c["accent"],
            selected_hover_color=c["accent_hover"],
            fg_color=c["card"],
            corner_radius=8,
        )
        seg.pack(fill="x", pady=(4, 0))

        self.custom_frame = ctk.CTkFrame(self, fg_color="transparent")
        if self.cfg.get("speed") == "custom":
            self.custom_frame.pack(fill="x", padx=self.PX, pady=(4, 0))
        cf = ctk.CTkFrame(self.custom_frame, fg_color="transparent")
        cf.pack(fill="x")
        for label_text, var_name, default in [
            ("Min:", "custom_min", 0.025),
            ("Max:", "custom_max", 0.04),
        ]:
            self._lbl(cf, label_text, size=11).pack(side="left", padx=(0, 2))
            v = ctk.StringVar(value=str(self.cfg.get(var_name, default)))
            setattr(self, f"_var_{var_name}", v)
            ctk.CTkEntry(
                cf,
                textvariable=v,
                width=60,
                height=24,
                font=ctk.CTkFont(size=11),
                fg_color=c["card"],
                border_color=c["card_border"],
                corner_radius=6,
            ).pack(side="left", padx=(0, 10))

        right_s = ctk.CTkFrame(row, fg_color="transparent")
        right_s.pack(side="right")
        self._lbl(right_s, "HOTKEY", size=10, weight="bold", color_key="text_dim").pack(
            anchor="e"
        )
        self.btn_hk = self._btn(
            right_s, self.cfg["hotkey"].upper(), self._on_hk_click, w=90, h=30
        )
        self.btn_hk.pack(pady=(4, 0))

        seg.set(self.cfg.get("speed", "medium"))

        self.btn_main = ctk.CTkButton(
            self,
            text="\u25b6  START",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            fg_color=c["accent"],
            hover_color=c["accent_hover"],
            text_color="#ffffff",
            width=380,
            height=44,
            corner_radius=12,
            command=self._toggle,
        )
        self.btn_main.pack(pady=(10, 6))

        self.lbl_diag = ctk.CTkLabel(
            self,
            text=("Bereit." + ("" if _KEYBOARD_OK else "  [keyboard-Modul fehlt!]")),
            font=ctk.CTkFont(family="Segoe UI", size=9),
            text_color=c["text_dim"],
            wraplength=380,
            justify="left",
            anchor="w",
        )
        self.lbl_diag.pack(fill="x", padx=self.PX, pady=(0, 4))

        self._lbl(
            self,
            "F6 = Start/Stop  \u2022  Bongo Cat muss offen sein (Fokus egal)",
            size=9,
            color_key="text_dim",
        ).pack()

        is_running = False
        if self.engine:
            with self.engine.lock:
                is_running = self.engine.running
        if is_running:
            self.lbl_status.configure(text="\u25cf Running", text_color=c["green"])
            self.btn_main.configure(
                text="\u25a0  STOP", fg_color=c["red"], hover_color=c["red_hover"]
            )

    def _on_speed_change(self, v):
        self.cfg["speed"] = v
        if v == "custom":
            self._save_custom()
            self.custom_frame.pack(fill="x", padx=self.PX, pady=(4, 0))
        else:
            self.custom_frame.pack_forget()
        save_config(self.cfg)

    def _save_custom(self):
        try:
            v = float(self._var_custom_min.get())
            self.cfg["custom_min"] = max(0.001, min(v, 1.0))
        except (ValueError, AttributeError):
            pass
        try:
            v = float(self._var_custom_max.get())
            self.cfg["custom_max"] = max(0.001, min(v, 1.0))
        except (ValueError, AttributeError):
            pass
        if self.cfg["custom_min"] > self.cfg["custom_max"]:
            self.cfg["custom_min"], self.cfg["custom_max"] = (
                self.cfg["custom_max"],
                self.cfg["custom_min"],
            )
        save_config(self.cfg)

    def _toggle_theme(self):
        self.cfg["theme"] = "light" if self.cfg.get("theme") == "dark" else "dark"
        save_config(self.cfg)
        ctk.set_appearance_mode(self.cfg["theme"])
        self._rebuilding = True
        try:
            self._build()
        finally:
            self._rebuilding = False
        self._fit_height()

    def _reg_hotkey(self):
        self._unhook_hotkey()
        if not _KEYBOARD_OK:
            log.error("keyboard-Modul fehlt - Hotkey deaktiviert")
            return
        hk = self.cfg.get("hotkey", "f6").lower()
        if not hk:
            return
        try:
            self._hk_handle = keyboard.on_press_key(hk, self._hk_fire, suppress=False)
            log.info("Hotkey aktiv: %s", hk)
        except Exception as e:
            log.warning("Hotkey '%s' nicht registrierbar: %s", hk, e)
            self._hk_handle = None

    def _unhook_hotkey(self):
        if self._hk_handle is not None and _KEYBOARD_OK:
            try:
                keyboard.unhook(self._hk_handle)
            except Exception:
                pass
            self._hk_handle = None

    def _hk_fire(self, event=None):
        if not self._alive:
            return
        log.info(
            "START via HOTKEY | vordergrund=0x%x", win32gui.GetForegroundWindow()
        )
        try:
            self.after(0, self._toggle)
        except Exception:
            pass

    def _on_hk_click(self):
        if self.listening or not _KEYBOARD_OK:
            return
        self.listening = True
        self.btn_hk.configure(text="...", state="disabled")
        was = False
        if self.engine:
            with self.engine.lock:
                if self.engine.running:
                    self.engine.stop()
                    was = True
        self._hk_resume = was
        self._hk_cap_handle = keyboard.hook(self._hk_capture_cb)
        self._hk_cap_timer = self.after(10000, self._hk_capture_timeout)

    def _hk_capture_cb(self, event):
        if event.event_type != keyboard.KEY_DOWN:
            return
        name = (event.name or "").lower()
        if not name or name in _MODIFIER_NAMES:
            return
        if len(name) < 15:
            self.cfg["hotkey"] = name
            save_config(self.cfg)
        self._finish_capture()

    def _hk_capture_timeout(self):
        if self.listening:
            self._finish_capture()

    def _finish_capture(self):
        if self._hk_cap_handle is not None and _KEYBOARD_OK:
            try:
                keyboard.unhook(self._hk_cap_handle)
            except Exception:
                pass
            self._hk_cap_handle = None
        if self._hk_cap_timer is not None:
            try:
                self.after_cancel(self._hk_cap_timer)
            except Exception:
                pass
            self._hk_cap_timer = None
        self.btn_hk.configure(
            text=self.cfg.get("hotkey", "f6").upper(), state="normal"
        )
        self.listening = False
        self._reg_hotkey()
        if self._hk_resume:
            self._hk_resume = False
            self._start_engine()

    def _reset_total(self):
        if self.engine:
            self.engine.reset()
        self.lbl_cps.configure(text="0 CPS")
        self.lbl_total.configure(text="0")
        self._cps_data.clear()
        self.cps_graph.reset_data()

    def _toggle(self):
        is_running = False
        if self.engine:
            with self.engine.lock:
                is_running = self.engine.running
        if is_running:
            self._stop()
        else:
            self._start_engine()

    def _start_engine(self):
        hwnd = find_bongo()
        if not hwnd:
            self.lbl_status.configure(
                text="\u25cf Bongo Cat nicht gefunden!", text_color=self._c()["orange"]
            )
            self.after(
                5000,
                lambda: self.lbl_status.configure(
                    text="\u25cf Stopped", text_color=self._c()["text_dim"]
                ),
            )
            return
        if self.cfg.get("speed") == "custom":
            self._save_custom()
        if not self.engine:
            self.engine = Engine(stats_cb=self._on_stats, cfg_ref=lambda: self.cfg)
        self.engine.start()
        log.info(
            "START via BUTTON | bongo hwnd=0x%x | vordergrund=0x%x | focus=clicker",
            hwnd, win32gui.GetForegroundWindow(),
        )
        c = self._c()
        self.lbl_status.configure(text="\u25cf Running", text_color=c["green"])
        self.btn_main.configure(
            text="\u25a0  STOP", fg_color=c["red"], hover_color=c["red_hover"]
        )

    def _stop(self):
        if self.engine:
            self.engine.stop()
        c = self._c()
        self.lbl_status.configure(text="\u25cf Stopped", text_color=c["red"])
        self.btn_main.configure(
            text="\u25b6  START", fg_color=c["accent"], hover_color=c["accent_hover"]
        )

    def _on_stats(self, cps, total):
        if self._alive:
            self.after(0, lambda: self._update_stats(cps, total))

    def _update_stats(self, cps, total):
        if not self._alive or self._rebuilding:
            return
        self._cps_data.append(cps)
        if len(self._cps_data) > 50:
            self._cps_data.pop(0)
        self.lbl_cps.configure(text=f"{cps:,.0f} CPS")
        self.lbl_total.configure(text=f"{total:,}")
        self.cps_graph.add_point(cps)

    def _diag_poll(self):
        if not self._alive:
            return
        try:
            d = getattr(self.engine, "diag", "Engine aus") if self.engine else "Engine aus"
            self.lbl_diag.configure(text=d)
        except Exception:
            pass
        self._diag_id = self.after(500, self._diag_poll)

    def _setup_tray(self):
        try:
            import pystray
        except ImportError:
            return

        def on_show(icon, _):
            self._tray_icon = None
            icon.stop()
            self.event_generate("<<ShowFromTray>>", when="tail")

        def on_quit(icon, _):
            self._tray_icon = None
            icon.stop()
            if self.engine:
                self.engine.stop()
            self._unhook_hotkey()
            self.event_generate("<<QuitFromTray>>", when="tail")

        self._tray_icon = pystray.Icon(
            "bongoclicker",
            create_tray_icon_image(),
            "Bongo Cat Clicker",
            pystray.Menu(
                pystray.MenuItem("Show", on_show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", on_quit),
            ),
        )
        self._tray_icon.run()

    def _on_quit_from_tray(self, event=None):
        self._alive = False
        self.after(100, self._on_close)

    def _on_minimize_to_tray(self):
        if self._tray_icon is not None:
            return
        self.withdraw()
        threading.Thread(target=self._setup_tray, daemon=True).start()

    def _on_close(self):
        if not self._alive:
            return
        self._alive = False
        if self.engine:
            self.engine.stop()
            self.engine.kill()
        self._unhook_hotkey()
        if self._hk_cap_handle is not None and _KEYBOARD_OK:
            try:
                keyboard.unhook(self._hk_cap_handle)
            except Exception:
                pass
            self._hk_cap_handle = None
        if self._diag_id is not None:
            try:
                self.after_cancel(self._diag_id)
            except Exception:
                pass
            self._diag_id = None
        try:
            self.quit()
            self.destroy()
        except Exception:
            pass

    def _show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()


def _single_instance():
    try:
        handle = win32event.CreateMutex(None, False, MUTEX_NAME)
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            return None
        return handle
    except Exception:
        return True


if __name__ == "__main__":
    mutex = _single_instance()
    if mutex is None:
        import tkinter.messagebox as mb

        mb.showwarning("Bongo Cat Clicker", "Bongo Cat Clicker laeuft bereits.")
        sys.exit(0)
    app = App()
    app._mutex = mutex
    app.mainloop()
