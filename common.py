"""Пути, настройки, темы, визуальный язык приложения."""
from __future__ import annotations
import json, os, sys, threading
from pathlib import Path

APP, VER = "LightRead", "1.1.0"
PDF_LOCK = threading.RLock()


def _base() -> Path:
    here = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    if any((here / n).exists() for n in ("portable.ini", "portable.txt")):
        return here / "data"
    if os.name == "nt":
        root = Path(os.getenv("APPDATA", str(Path.home())))
    elif sys.platform == "darwin":
        root = Path.home() / "Library/Application Support"
    else:
        root = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / APP


DATA = _base(); CACHE = DATA / "cache"; COVERS = DATA / "covers"
for _d in (DATA, CACHE, COVERS):
    _d.mkdir(parents=True, exist_ok=True)
DB = str(DATA / "library.db")
SETFILE = DATA / "settings.json"

# Чернила и бумага: тёплый бумажный свет, холодные чернильные поверхности,
# оранжевый маркер как доминантный акцент, синий — ссылки, зелёный — прогресс.
THEMES = {
    "День":     dict(bg="#fdfbf7", fg="#23211e", link="#2f6f9e", sel="#f5dda9", dark=False, desk="#cbc5b9"),
    "Сепия":    dict(bg="#f6ecd8", fg="#3b3224", link="#8a6335", sel="#e5c99e", dark=False, desk="#b7a282"),
    "Ночь":     dict(bg="#15181e", fg="#ced3da", link="#8ab4f8", sel="#344057", dark=True,  desk="#0c0e12"),
    "AMOLED":   dict(bg="#000000", fg="#b8bdc5", link="#7aa7f7", sel="#222b3a", dark=True,  desk="#000000"),
    "Контраст": dict(bg="#000000", fg="#ffffff", link="#ffd24a", sel="#4a4a4a", dark=True,  desk="#000000"),
    "Зелень":   dict(bg="#dce8d8", fg="#1d2b1e", link="#216039", sel="#b3d0ae", dark=False, desk="#98ac95"),
    # Режимы ReadEra: сумерки (тёплый тусклый свет) и консоль (зелёный терминал).
    "Сумерки":  dict(bg="#2b211b", fg="#c9b8a5", link="#e0a96d", sel="#5a4534", dark=True,  desk="#16100c"),
    "Консоль":  dict(bg="#04140a", fg="#8dffb0", link="#b6ff5c", sel="#1f4d2d", dark=True,  desk="#010804"),
}
HL = ["#f0b552", "#63cf8a", "#57bfe8", "#ef8fbd", "#b79ce6"]

ACCENT = "#ec8f5a"
ACCENT2 = "#4c8dff"
OK = "#3ecf8e"
WARN = "#ffc94a"
BAD = "#ff5470"

DEFAULTS = dict(
    font_family="", font_size=15, bold=False, line_spacing=136, indent=20, para_space=0,
    align="justify", margin=30, gap=36, columns=1, mode="paged", theme="Сепия", brightness=1.0,
    tap_zones=True, wheel_pages=True,
    pdf_fit="width", pdf_zoom=100, pdf_crop=False, pdf_invert=True, pdf_gap=18,
    pdf_shadow=True, render_scale=1.5,
    tts_voice="", tts_rate=0.0, tts_pitch=0.0, tts_vol=1.0, tts_follow=True,
    autoscroll=45, folders=[], scan_on_start=False, view="grid", sort="added_desc",
    dict_paths=[], save_per_book=False, tune_visible=True,
)


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            self.update(json.loads(SETFILE.read_text("utf-8")))
        except Exception:
            pass
        for k, v in DEFAULTS.items():
            self.setdefault(k, v)

    def save(self):
        try:
            SETFILE.write_text(json.dumps(self, ensure_ascii=False, indent=1), "utf-8")
        except Exception:
            pass


S = Settings()


def theme(name=None):
    return THEMES.get(name or S["theme"], THEMES["Сепия"])


def human(n):
    n = float(n or 0)
    for u in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "Б" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} ТБ"


def hms(sec):
    sec = int(sec or 0); h, m = sec // 3600, (sec % 3600) // 60
    return (f"{h} ч " if h else "") + f"{m} мин"


def norm(p):
    return str(Path(p)).replace("\\", "/")


