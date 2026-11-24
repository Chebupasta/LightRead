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
    # Холодная нейтральная шкала: каждый шаг заметно отличается от соседнего.
    "ink.980": "#050608", "ink.950": "#08090b", "ink.940": "#0a0b0e",
    "ink.920": "#0f1116", "ink.900": "#0d0e12", "ink.880": "#141720",
    "ink.850": "#121318", "ink.840": "#1a1e28", "ink.800": "#16181f",
    "ink.780": "#20252f", "ink.750": "#1c1f27", "ink.720": "#28303d",
    "ink.700": "#242832", "ink.680": "#333c4c", "ink.640": "#3b4455",
    "ink.600": "#303542",
    "ink.500": "#464c5b", "ink.450": "#5d6676", "ink.400": "#6b7280",
    "ink.350": "#7d8697", "ink.300": "#949ba9", "ink.250": "#a8b0be",
    "ink.200": "#b9bfcb", "ink.100": "#e7e9ee", "ink.50": "#f4f6f9",
    "paper.0": "#ffffff", "paper.25": "#fdfdfe", "paper.50": "#fbfbfc",
    "paper.75": "#f7f9fb", "paper.100": "#f5f6f7", "paper.150": "#f1f3f6",
    "paper.200": "#eceef0", "paper.250": "#e6eaf0", "paper.300": "#dfe2e6",
    "paper.350": "#d7dde5", "paper.400": "#c9cdd4", "paper.450": "#b9c1cd",
    "paper.500": "#8b909b", "paper.550": "#7a8492", "paper.600": "#646a76",
    "paper.650": "#5a6473", "paper.700": "#3c424e", "paper.750": "#3a4351",
    "paper.800": "#232832", "paper.850": "#202632", "paper.900": "#151a23",
    "indigo.050": "#eef0ff", "indigo.950": "#1b2340",
    "indigo.300": "#8b93ff", "indigo.400": "#7170ff",
    "indigo.500": "#5e6ad2", "indigo.600": "#4b55b8",
    "green.400": "#4ac98a", "green.500": "#3fb950", "green.700": "#1a7f37",
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
        # Поверхности: каждая роль — отдельный уровень, а не оттенок ±2.
        "bg.canvas": _c("ink.950"),   # фон окна, самый глубокий
        "bg.overlay": _c("ink.900"),  # затемнение под диалогами
        "bg.field": _c("ink.940"),    # поля ввода — утоплены
        "bg.panel": _c("ink.920"),    # меню, тулбары, статус-бар
        "bg.subtle": _c("ink.880"),   # треки, чипы, второстепенные заливки
        "bg.raised": _c("ink.840"),   # карточки, тосты, continue card
        "bg.hover": _c("ink.780"),
        "bg.selected": _c("ink.720"),
        "bg.active": _c("ink.680"),
        "border.subtle": _c("ink.700"),
        "border.strong": _c("ink.640"),
        "border.focus": _c("indigo.500"),
        "text.primary": _c("ink.50"),
        "text.secondary": _c("ink.250"),
        "text.tertiary": _c("ink.350"),
        "text.disabled": _c("ink.450"),
        "text.on_accent": _c("paper.0"),
        "accent.default": _c("indigo.500"),
        "accent.hover": _c("indigo.400"),
        "accent.subtle": _c("indigo.950"),
        "status.success": _c("green.400"), "status.warning": _c("amber.500"),
        "status.danger": _c("red.500"), "status.info": _c("blue.500"),
        "status.neutral": _c("ink.350"),
        "data.pdf": _c("red.500"), "data.epub": _c("green.400"),
        "data.fb2": _c("indigo.400"), "data.djvu": _c("violet.500"),
        "data.docx": _c("blue.500"), "data.mobi": _c("amber.500"),
        "data.azw3": _c("amber.500"), "data.txt": _c("ink.350"),
        "data.pptx": _c("amber.500"), "data.odp": _c("amber.500"),
        "data.ppt": _c("amber.500"), "data.pps": _c("amber.500"),
        "data.ppsx": _c("amber.500"), "data.otp": _c("amber.500"),
        "shadow": "#80000000",
    },
    "light": {
        "bg.canvas": _c("paper.0"),
        "bg.overlay": _c("paper.75"),
        "bg.field": _c("paper.25"),
        "bg.panel": _c("paper.50"),
        "bg.subtle": _c("paper.100"),
        "bg.raised": _c("paper.150"),
        "bg.hover": _c("paper.200"),
        "bg.selected": _c("paper.300"),
        "bg.active": _c("paper.400"),
        "border.subtle": _c("paper.350"),
        "border.strong": _c("paper.450"),
        "border.focus": _c("indigo.500"),
        "text.primary": _c("paper.900"),
        "text.secondary": _c("paper.650"),
        "text.tertiary": _c("paper.550"),
        "text.disabled": _c("paper.450"),
        "text.on_accent": _c("paper.0"),
        "accent.default": _c("indigo.500"),
        "accent.hover": _c("indigo.600"),
        "accent.subtle": _c("indigo.050"),
        "status.success": _c("green.700"), "status.warning": _c("amber.700"),
        "status.danger": _c("red.700"), "status.info": _c("blue.700"),
        "status.neutral": _c("paper.550"),
        "data.pdf": _c("red.700"), "data.epub": _c("green.700"),
        "data.fb2": _c("indigo.600"), "data.djvu": _c("violet.700"),
        "data.docx": _c("blue.700"), "data.mobi": _c("amber.700"),
        "data.azw3": _c("amber.700"), "data.txt": _c("paper.550"),
        "data.pptx": _c("amber.700"), "data.odp": _c("amber.700"),
        "data.ppt": _c("amber.700"), "data.pps": _c("amber.700"),
        "data.ppsx": _c("amber.700"), "data.otp": _c("amber.700"),
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
    s["accent.subtle"] = accent[2] if th["dark"] else accent[3]
    s["border.focus"] = accent[0]
    c = dict(s)
    c.update(
        win=s["bg.canvas"], panel=s["bg.panel"], field=s["bg.field"],
        raised=s["bg.raised"], active=s["bg.active"], disabled=s["text.disabled"],
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
    office_pdf=True, office_cache_days=30, office_cache_mb=512, swipe_nav=True,
    auto_theme=False, theme_day_start=7, theme_night_start=20,
    pomodoro_work=25, pomodoro_break=5,
    auto_git_update=False, update_repo="", language="ru",
)

ACCENTS = {
    # default, hover, subtle-dark, subtle-light
    "indigo": ("#5e6ad2", "#7170ff", "#1b2340", "#eef0ff"),
    "teal": ("#2f9e93", "#4fc3b7", "#102824", "#e8f5f2"),
    "violet": ("#8250df", "#a371f7", "#23163b", "#f2ebff"),
    "amber": ("#b8860b", "#d29922", "#2a2108", "#fff6e0"),
}


PRESENTATION_FMTS = ("pptx", "ppt", "pps", "ppsx", "potx", "odp", "otp")
OFFICE_FMTS = ("docx", "docm", "dotx", "doc", "dot", "rtf", "odt", "ott") + PRESENTATION_FMTS


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


