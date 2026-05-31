import json
import os
import random
import shutil
import threading
import time
import zipfile

import customtkinter as ctk
import keyboard
import pydirectinput
import win32con
import win32gui
from PIL import Image, ImageDraw

pydirectinput.PAUSE = 0

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".bongoclicker.json")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, "cat.ico")
MOD_ZIP = os.path.join(SCRIPT_DIR, "BongoCatMod.zip")
MOD_CONFIG_NAME = "com.seraphli.bongocatmod.cfg"
BONGO_TITLES = ["BongoCat", "Bongo Cat"]
EXCLUDE_TITLES = ["clicker", "bot"]
SPAM_CHARS = list("abcdeghijklmnopqstuvwxyz0123456789")
HOLD_MIN = 0.035
HOLD_MAX = 0.055
SPEED_PRESETS = {
    "slow": (0.06, 0.09, 0.035, 0.055),
    "medium": (0.025, 0.04, 0.035, 0.055),
    "fast": (0.001, 0.003, 0.020, 0.030),
    "custom": (0.025, 0.04, 0.035, 0.055),
}
DEFAULT_CONFIG = {
    "hotkey": "f6",
    "theme": "dark",
    "speed": "medium",
    "custom_min": 0.025,
    "custom_max": 0.04,
}

BONGO_INSTALL = None
for _sp in [
    os.path.join(
        os.environ.get("ProgramFiles(x86)", ""), "Steam", "steamapps", "common"
    ),
    os.path.join(os.environ.get("ProgramFiles", ""), "Steam", "steamapps", "common"),
]:
    _c = os.path.join(_sp, "BongoCat")
    if os.path.isfile(os.path.join(_c, "BongoCat.exe")):
        BONGO_INSTALL = _c
        break

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


# ── Helpers ──
def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def find_bongo():
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
    return results[0] if results else None


def focus_bongo():
    hwnd = find_bongo()
    if hwnd and win32gui.IsWindow(hwnd):
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return True
    return False


# ── Mod Management ──
def find_bongo_install():
    if BONGO_INSTALL and os.path.isfile(os.path.join(BONGO_INSTALL, "BongoCat.exe")):
        return BONGO_INSTALL
    return None


def is_mod_installed():
    g = find_bongo_install()
    return g and os.path.isfile(
        os.path.join(g, "BepInEx", "plugins", "BongoCatMod.dll")
    )


def get_mod_config_path():
    g = find_bongo_install()
    return os.path.join(g, "BepInEx", "config", MOD_CONFIG_NAME) if g else None


def read_mod_config():
    p = get_mod_config_path()
    if not p or not os.path.isfile(p):
        return None, None
    ab, cm = None, None
    try:
        with open(p) as f:
            for line in f:
                s = line.strip()
                if s.startswith("AutoBuyEnabled"):
                    ab = s.split("=")[1].strip().lower() == "true"
                elif s.startswith("ClickMultiplier"):
                    cm = int(s.split("=")[1].strip())
    except Exception:
        pass
    return ab, cm


def write_mod_config(enabled=None, multiplier=None):
    p = get_mod_config_path()
    if not p:
        return False
    lines = []
    if os.path.isfile(p):
        with open(p) as f:
            lines = f.readlines()
    fb, fm = False, False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("AutoBuyEnabled") and enabled is not None:
            lines[i] = f"AutoBuyEnabled = {'true' if enabled else 'false'}\n"
            fb = True
        elif s.startswith("ClickMultiplier") and multiplier is not None:
            lines[i] = f"ClickMultiplier = {multiplier}\n"
            fm = True
    if not fb and enabled is not None:
        if not any("[General]" in x for x in lines):
            lines.append("[General]\n")
        lines.append(f"AutoBuyEnabled = {'true' if enabled else 'false'}\n")
    if not fm and multiplier is not None:
        lines.append(f"ClickMultiplier = {multiplier}\n")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.writelines(lines)
    return True


def do_install_mod():
    g = find_bongo_install()
    if not g:
        return False, "Bongo Cat nicht gefunden!"
    if not os.path.isfile(MOD_ZIP):
        return False, "BongoCatMod.zip fehlt!"
    try:
        with zipfile.ZipFile(MOD_ZIP) as z:
            z.extractall(g)
        cp = os.path.join(g, "BepInEx", "config", MOD_CONFIG_NAME)
        if not os.path.isfile(cp):
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            with open(cp, "w") as f:
                f.write("[General]\nAutoBuyEnabled = true\nClickMultiplier = 1\n")
        return True, "Mod installiert! Bongo Cat neu starten."
    except Exception as e:
        return False, f"Fehler: {e}"


def do_uninstall_mod():
    g = find_bongo_install()
    if not g:
        return False, "Bongo Cat nicht gefunden!"
    removed = []
    for t in ["BepInEx", "doorstop_config.ini", "winhttp.dll", ".doorstop_version"]:
        p = os.path.join(g, t)
        if os.path.isdir(p):
            shutil.rmtree(p)
            removed.append(t)
        elif os.path.isfile(p):
            os.remove(p)
            removed.append(t)
    if removed:
        return True, f"Entfernt: {', '.join(removed)}. Neustart!"
    return True, "Nicht installiert."


# ── Icon ──
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
    for pts, dx in [
        [(cx - 60, cy - 64), (cx - 62, cy - 118), (cx - 12, cy - 68)],
        None,
    ]:
        pass
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
    d.ellipse([cx + 3, cy - 5, cx + 11, cy + 3], fill="white")
    d.ellipse([cx + 3, cy - 5, cx + 11, cy + 3], fill="white")
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


# ── Engine ──
class Engine:
    def __init__(self, stats_cb, cfg):
        self.running = False
        self.lock = threading.Lock()
        self._stats_cb = stats_cb
        self._cfg = cfg
        self.total = 0
        self.cps = 0.0
        self._wc = 0
        self._ws = time.time()
        threading.Thread(target=self._loop, daemon=True).start()

    def start(self):
        with self.lock:
            self.running = True

    def stop(self):
        with self.lock:
            self.running = False

    def reset(self):
        with self.lock:
            self.total = 0
            self.cps = 0.0
            self._wc = 0
            self._ws = time.time()

    def _get_intervals(self):
        p = self._cfg.get("speed", "medium")
        if p == "custom":
            return (
                self._cfg.get("custom_min", 0.025),
                self._cfg.get("custom_max", 0.04),
                HOLD_MIN,
                HOLD_MAX,
            )
        return SPEED_PRESETS.get(p, SPEED_PRESETS["medium"])

    def _loop(self):
        lf = 0.0
        while True:
            with self.lock:
                if not self.running:
                    time.sleep(0.05)
                    continue
            now = time.time()
            if now - lf > 2.0:
                focus_bongo()
                lf = now
            imin, imax, hmin, hmax = self._get_intervals()
            try:
                k = random.choice(SPAM_CHARS)
                pydirectinput.keyDown(k)
                time.sleep(random.uniform(hmin, hmax))
                pydirectinput.keyUp(k)
                self.total += 1
                self._wc += 1
            except Exception:
                pass
            now = time.time()
            if now - self._ws >= 0.4:
                self.cps = self._wc / (now - self._ws)
                self._wc = 0
                self._ws = now
                if self._stats_cb:
                    try:
                        self._stats_cb(self.cps, self.total)
                    except Exception:
                        pass
            time.sleep(random.uniform(imin, imax))


# ── App ──
class App(ctk.CTk):
    W, PX, PY = 420, 20, 0  # width, padding-x, padding-y base

    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.engine = None
        self.hook = None
        self.listening = False
        self._alive = True
        self._tray_icon = None

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
        self.geometry("420x560")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_minimize_or_close)
        self._build()
        self._reg_hotkey()

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

        # ── Row 1: Header ──
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=self.PX, pady=(12, 0))
        ctk.CTkLabel(
            row,
            text="Bongo Cat Clicker",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=c["text"],
        ).pack(side="left")
        self._btn(
            row,
            "\u2600\ufe0f" if c == DARK else "\U0001f319",
            self._toggle_theme,
            w=34,
            h=34,
        ).pack(side="right")

        # ── Row 2: CPS Card (compact) ──
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

        # ── Row 3: Speed + Hotkey side by side ──
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
        seg.set(self.cfg.get("speed", "medium"))

        # Custom speed row (hidden by default)
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

        # ── Row 4: Mod Section ──
        self._divider(self)
        mod_installed = is_mod_installed()
        game_found = find_bongo_install() is not None
        mod_enabled, mod_mult = read_mod_config()

        sec = ctk.CTkFrame(self, fg_color="transparent")
        sec.pack(fill="x", padx=self.PX)

        # Mod header
        hdr = ctk.CTkFrame(sec, fg_color="transparent")
        hdr.pack(fill="x")
        self._lbl(
            hdr, "\U0001f4e6 AUTO-CHEST", size=11, weight="bold", color_key="text_dim"
        ).pack(side="left")

        if mod_installed and mod_enabled is not None:
            st = "\u2705 AN" if mod_enabled else "\u26d4 AUS"
            sc = c["green"] if mod_enabled else c["text_dim"]
        elif game_found:
            st, sc = "\u26a0 nicht installiert", c["orange"]
        else:
            st, sc = "\u274c Spiel nicht gefunden", c["red"]
        ctk.CTkLabel(
            hdr, text=st, font=ctk.CTkFont(family="Segoe UI", size=11), text_color=sc
        ).pack(side="right")

        if mod_installed:
            btns = ctk.CTkFrame(sec, fg_color="transparent")
            btns.pack(fill="x", pady=(6, 0))
            self._btn(
                btns,
                "AUS" if mod_enabled else "AN",
                self._toggle_mod,
                w=60,
                h=26,
                accent=not mod_enabled,
            ).pack(side="left")
            self._btn(
                btns, "Entfernen", self._uninstall_mod, w=70, h=26, danger=True
            ).pack(side="left", padx=6)

            # Multiplier inline
            mult = mod_mult if mod_mult else 1
            self._lbl(
                btns, f"x{mult}", size=13, weight="bold", color_key="accent"
            ).pack(side="right")

            self.slider_mult = ctk.CTkSlider(
                sec,
                from_=1,
                to=5000,
                number_of_steps=50,
                fg_color=c["card_border"],
                progress_color=c["accent"],
                button_color=c["accent"],
                button_hover_color=c["accent_hover"],
                command=self._on_mult_change,
            )
            self.slider_mult.set(mult)
            self.slider_mult.pack(fill="x", pady=(6, 0))

            self._lbl(
                sec,
                "1 = normal  \u2022  1000 = Truhe sofort",
                size=9,
                color_key="text_dim",
            ).pack(anchor="w", pady=(2, 0))
        elif game_found:
            self._btn(
                sec,
                "\U0001f4e6 Mod installieren",
                self._install_mod,
                w=380,
                h=32,
                accent=True,
            ).pack(pady=(6, 0))

        self.lbl_mod_msg = self._lbl(self, "", size=10, color_key="text_dim")
        self.lbl_mod_msg.pack(pady=(2, 0))

        # ── Row 5: Start/Stop ──
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

        self._lbl(
            self,
            "X \u2192 Tray  \u2022  Bongo Cat must be running",
            size=9,
            color_key="text_dim",
        ).pack()

        # Restore running state
        if self.engine and self.engine.running:
            self.lbl_status.configure(text="\u25cf Running", text_color=c["green"])
            self.btn_main.configure(
                text="\u25a0  STOP", fg_color=c["red"], hover_color=c["red_hover"]
            )

    # ── Mod actions ──
    def _install_mod(self):
        def do():
            ok, msg = do_install_mod()
            self.after(0, lambda: self._mod_result(ok, msg))

        threading.Thread(target=do, daemon=True).start()

    def _uninstall_mod(self):
        def do():
            ok, msg = do_uninstall_mod()
            self.after(0, lambda: self._mod_result(ok, msg))

        threading.Thread(target=do, daemon=True).start()

    def _toggle_mod(self):
        cur, _ = read_mod_config()
        write_mod_config(enabled=not (cur if cur is not None else True))
        self._build()

    def _on_mult_change(self, v):
        val = int(v)
        write_mod_config(multiplier=val)
        self._build()

    def _mod_result(self, ok, msg):
        self.lbl_mod_msg.configure(text=msg)
        if ok:
            self._build()

    # ── Speed ──
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
            self.cfg["custom_min"] = float(self._var_custom_min.get())
        except (ValueError, AttributeError):
            pass
        try:
            self.cfg["custom_max"] = float(self._var_custom_max.get())
        except (ValueError, AttributeError):
            pass
        save_config(self.cfg)

    # ── Theme ──
    def _toggle_theme(self):
        self.cfg["theme"] = "light" if self.cfg.get("theme") == "dark" else "dark"
        save_config(self.cfg)
        ctk.set_appearance_mode(self.cfg["theme"])
        self._build()

    # ── Hotkey ──
    def _reg_hotkey(self):
        if self.hook:
            try:
                keyboard.unhook(self.hook)
            except Exception:
                pass
        hk = self.cfg.get("hotkey", "f6").lower()
        try:
            self.hook = keyboard.on_press_key(hk, lambda _: self.after(0, self._toggle))
        except Exception:
            self.hook = None

    def _on_hk_click(self):
        if self.listening:
            return
        self.listening = True
        self.btn_hk.configure(text="...", state="disabled")
        was = self.engine and self.engine.running
        if was:
            self.engine.stop()
        threading.Thread(target=self._capture_key, args=(was,), daemon=True).start()

    def _capture_key(self, resume):
        name = None
        ev = threading.Event()

        def on(e):
            nonlocal name
            if e.event_type == keyboard.KEY_DOWN and e.name:
                name = e.name
                ev.set()
                return False

        h = keyboard.hook(on)
        ev.wait(timeout=10)
        keyboard.unhook(h)
        if self._alive and name and len(name) < 15:
            self.cfg["hotkey"] = name.lower()
            save_config(self.cfg)
        if self._alive:
            self.after(0, lambda: self._finish_capture(resume))

    def _finish_capture(self, resume):
        self.btn_hk.configure(text=self.cfg["hotkey"].upper(), state="normal")
        self.listening = False
        self._reg_hotkey()
        if resume:
            self._start_engine()

    # ── Engine ──
    def _reset_total(self):
        if self.engine:
            self.engine.reset()
        self.lbl_cps.configure(text="0 CPS")
        self.lbl_total.configure(text="0")

    def _toggle(self):
        if self.engine and self.engine.running:
            self._stop()
        else:
            self._start_engine()

    def _start_engine(self):
        if not find_bongo():
            self.lbl_status.configure(
                text="\u25cf Bongo Cat nicht gefunden!", text_color=self._c()["orange"]
            )
            return
        if self.cfg.get("speed") == "custom":
            self._save_custom()
        if not self.engine:
            self.engine = Engine(stats_cb=self._on_stats, cfg=self.cfg)
        self.engine.start()
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
        if not self._alive:
            return
        self.lbl_cps.configure(text=f"{cps:,.0f} CPS")
        self.lbl_total.configure(text=f"{total:,}")

    # ── Tray ──
    def _setup_tray(self):
        try:
            import pystray
        except ImportError:
            return

        def on_show(icon, _):
            icon.stop()
            self.after(0, self._show_window)

        def on_quit(icon, _):
            self._alive = False
            if self.engine:
                self.engine.stop()
            if self.hook:
                try:
                    keyboard.unhook(self.hook)
                except:
                    pass
            icon.stop()
            self.after(0, self._real_close)

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

    def _on_minimize_or_close(self):
        self.withdraw()
        threading.Thread(target=self._setup_tray, daemon=False).start()

    def _show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _real_close(self):
        try:
            self.quit()
            self.destroy()
        except:
            pass

    def _on_close(self):
        self._alive = False
        if self.engine:
            self.engine.stop()
        if self.hook:
            try:
                keyboard.unhook(self.hook)
            except:
                pass
        self.quit()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
