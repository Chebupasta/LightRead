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

# Страница остаётся чистой бумагой/чистым чёрным — это область чтения.
# Вокруг неё строится оформление приложения на приглушённых поверхностях.
THEMES = {
    "Светлая": dict(bg="#ffffff", fg="#000000", link="#4b55b8", sel="#d3e3fd", dark=False, desk="#fbfbfc"),
    "Тёмная":  dict(bg="#000000", fg="#ffffff", link="#8b93ff", sel="#2b3a4f", dark=True,  desk="#08090b"),
}
# Все старые названия сводятся к двум новым темам.
THEME_ALIASES = {
    "День": "Светлая", "Сепия": "Светлая", "Лён": "Светлая", "Зелень": "Светлая",
    "Ночь": "Тёмная", "AMOLED": "Тёмная", "Сумерки": "Тёмная", "Графит": "Тёмная",
    "Контраст": "Тёмная", "Консоль": "Тёмная",
}
HL = ["#f0b552", "#63cf8a", "#57bfe8", "#ef8fbd", "#b79ce6"]

# ── Уровень 1: primitive — сырые шкалы, не зависящие от темы ────────────
COLOR = {
    "ink.950": "#08090b", "ink.900": "#0d0e12", "ink.850": "#121318",
    "ink.800": "#16181f", "ink.750": "#1c1f27", "ink.700": "#242832",
    "ink.600": "#303542", "ink.500": "#464c5b", "ink.400": "#6b7280",
    "ink.300": "#949ba9", "ink.200": "#b9bfcb", "ink.100": "#e7e9ee",
    "paper.0": "#ffffff", "paper.50": "#fbfbfc", "paper.100": "#f5f6f7",
    "paper.200": "#eceef0", "paper.300": "#dfe2e6", "paper.400": "#c9cdd4",
    "paper.500": "#8b909b", "paper.600": "#646a76", "paper.700": "#3c424e",
    "paper.800": "#232832",
    "indigo.300": "#8b93ff", "indigo.400": "#7170ff",
    "indigo.500": "#5e6ad2", "indigo.600": "#4b55b8",
    "green.500": "#3fb950", "green.700": "#1a7f37",
    "amber.500": "#d29922", "amber.700": "#9a6700",
    "red.500": "#f85149", "red.700": "#cf222e",
    "blue.500": "#58a6ff", "blue.700": "#0969da",
    "violet.500": "#a371f7", "violet.700": "#8250df",
}
SPACE = dict(xs=2, sm=4, md=8, lg=12, xl=16, xxl=24)
RADIUS = dict(xs=2, sm=4, md=6)
FONT = dict(size=dict(xs=10, sm=11, md=12, lg=13, xl=15),
            weight=dict(regular=400, medium=500))
PRIMITIVE = dict(color=COLOR, space=SPACE, radius=RADIUS, font=FONT)

# ── Уровень 2: semantic — роли, привязанные к primitive ─────────────────
_c = COLOR.__getitem__

SEMANTIC = {
    "dark": {
        "bg.canvas": _c("ink.950"), "bg.panel": _c("ink.900"),
        "bg.field": _c("ink.850"), "bg.subtle": _c("ink.800"),
        "bg.hover": _c("ink.750"), "bg.selected": _c("ink.700"),
        "bg.overlay": _c("ink.800"),
        "border.subtle": _c("ink.700"), "border.strong": _c("ink.600"),
        "border.focus": _c("indigo.500"),
        "text.primary": _c("ink.100"), "text.secondary": _c("ink.300"),
        "text.tertiary": _c("ink.400"), "text.on_accent": _c("paper.0"),
        "accent.default": _c("indigo.500"), "accent.hover": _c("indigo.400"),
        "accent.subtle": _c("ink.700"),
        "status.success": _c("green.500"), "status.warning": _c("amber.500"),
        "status.danger": _c("red.500"), "status.info": _c("blue.500"),
        "status.neutral": _c("ink.400"),
        "data.pdf": _c("red.500"), "data.epub": _c("green.500"),
        "data.fb2": _c("indigo.400"), "data.djvu": _c("violet.500"),
        "data.docx": _c("blue.500"), "data.mobi": _c("amber.500"),
        "data.azw3": _c("amber.500"), "data.txt": _c("ink.400"),
        "shadow": "#80000000",
    },
    "light": {
        "bg.canvas": _c("paper.0"), "bg.panel": _c("paper.50"),
        "bg.field": _c("paper.0"), "bg.subtle": _c("paper.100"),
        "bg.hover": _c("paper.200"), "bg.selected": _c("paper.200"),
        "bg.overlay": _c("paper.50"),
        "border.subtle": _c("paper.300"), "border.strong": _c("paper.400"),
        "border.focus": _c("indigo.500"),
        "text.primary": _c("paper.800"), "text.secondary": _c("paper.600"),
        "text.tertiary": _c("paper.500"), "text.on_accent": _c("paper.0"),
        "accent.default": _c("indigo.500"), "accent.hover": _c("indigo.600"),
        "accent.subtle": _c("paper.200"),
        "status.success": _c("green.700"), "status.warning": _c("amber.700"),
        "status.danger": _c("red.700"), "status.info": _c("blue.700"),
        "status.neutral": _c("paper.500"),
        "data.pdf": _c("red.700"), "data.epub": _c("green.700"),
        "data.fb2": _c("indigo.600"), "data.djvu": _c("violet.700"),
        "data.docx": _c("blue.700"), "data.mobi": _c("amber.700"),
        "data.azw3": _c("amber.700"), "data.txt": _c("paper.500"),
        "shadow": "#16000000",
    },
}


# ── Уровень 3: chrome — готовый словарь для QSS и QPalette ──────────────
def chrome(th):
    """Семантические роли + legacy-ключи + размерные токены для QSS."""
    s = dict(SEMANTIC["dark" if th["dark"] else "light"])
    accent = ACCENTS.get(S.get("accent", "indigo"), ACCENTS["indigo"])
    s["accent.default"] = accent[0]
    s["accent.hover"] = accent[1]
    s["border.focus"] = accent[0]
    c = dict(s)
    c.update(
        win=s["bg.canvas"], panel=s["bg.panel"], field=s["bg.field"],
        border=s["border.subtle"], text=s["text.primary"], dim=s["text.secondary"],
        hover=s["bg.hover"], sel=s["bg.selected"], accent=s["accent.default"],
        onaccent=s["text.on_accent"], accent2=s["accent.hover"],
        track=s["bg.subtle"], thumb=s["border.strong"], divider=s["border.subtle"],
        chip=s["bg.subtle"], shadow=s["shadow"], page=th["desk"],
    )
    for k, v in SPACE.items():
        c[f"space.{k}"] = f"{v}px"
    for k, v in RADIUS.items():
        c[f"radius.{k}"] = f"{v}px"
    for k, v in FONT["size"].items():
        c[f"font.{k}"] = f"{v}px"
    for k, v in FONT["weight"].items():
        c[f"font.weight.{k}"] = str(v)
    return c


ACCENT = SEMANTIC["dark"]["accent.default"]
ACCENT2 = SEMANTIC["dark"]["accent.hover"]
OK = SEMANTIC["dark"]["status.success"]
WARN = SEMANTIC["dark"]["status.warning"]
BAD = SEMANTIC["dark"]["status.danger"]

DEFAULTS = dict(
    font_family="", font_size=15, bold=False, line_spacing=136, indent=20, para_space=0,
    align="justify", margin=30, gap=36, columns=1, mode="paged", theme="Светлая", brightness=1.0,
    tap_zones=True, wheel_pages=True,
    pdf_fit="width", pdf_zoom=100, pdf_crop=False, pdf_invert=True, pdf_gap=18,
    pdf_shadow=True, render_scale=1.5,
    tts_voice="", tts_rate=0.0, tts_pitch=0.0, tts_vol=1.0, tts_follow=True,
    autoscroll=45, folders=[], scan_on_start=False, view="grid", sort="added_desc",
    dict_paths=[], save_per_book=False, tune_visible=True,
    session_tabs=[], session_active=None, session_groups={}, smart=[], daily_goal=0,
    accent="indigo", opds=[], webdav_url="", webdav_user="", webdav_password="", webdav_auto=False,
    update_url="", update_auto=False, hyphenate=False, show_network=False, note_drafts={},
)

ACCENTS = {
    "indigo": ("#5e6ad2", "#7170ff", "#4b55b8"),
    "teal": ("#2f9e93", "#4fc3b7", "#26786f"),
    "violet": ("#8250df", "#a371f7", "#6339b5"),
    "amber": ("#b8860b", "#d29922", "#8a6508"),
}


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
    s = os.path.abspath(os.path.normpath(str(p)))
    if os.name == "nt":
        s = s.lower()
    return s.replace("\\", "/")


