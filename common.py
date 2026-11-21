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
# Только две темы: чистая белая и чистая чёрная. Никаких оттенков,
# которые ломают контраст и делают текст нечитаемым.
THEMES = {
    "Светлая": dict(bg="#ffffff", fg="#000000", link="#0b57d0", sel="#d3e3fd", dark=False, desk="#ffffff"),
    "Тёмная":  dict(bg="#000000", fg="#ffffff", link="#8ab4f8", sel="#333333", dark=True,  desk="#000000"),
}
# Все старые названия сводятся к двум новым темам.
THEME_ALIASES = {
    "День": "Светлая", "Сепия": "Светлая", "Лён": "Светлая", "Зелень": "Светлая",
    "Ночь": "Тёмная", "AMOLED": "Тёмная", "Сумерки": "Тёмная", "Графит": "Тёмная",
    "Контраст": "Тёмная", "Консоль": "Тёмная",
}
HL = ["#f0b552", "#63cf8a", "#57bfe8", "#ef8fbd", "#b79ce6"]

ACCENT = "#2f6fe0"
ACCENT2 = "#2f6fe0"
OK = "#3ecf8e"
WARN = "#ffc94a"
BAD = "#ff5470"

DEFAULTS = dict(
    font_family="", font_size=15, bold=False, line_spacing=136, indent=20, para_space=0,
    align="justify", margin=30, gap=36, columns=1, mode="paged", theme="Светлая", brightness=1.0,
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
        if self.get("theme") in THEME_ALIASES:
            self["theme"] = THEME_ALIASES[self["theme"]]

    def save(self):
        try:
            SETFILE.write_text(json.dumps(self, ensure_ascii=False, indent=1), "utf-8")
        except Exception:
            pass


S = Settings()


def norm_theme(name=None):
    name = THEME_ALIASES.get(name, name)
    return name if name in THEMES else "Светлая"


def theme(name=None):
    return THEMES[norm_theme(name or S["theme"])]


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


