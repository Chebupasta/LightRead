"""Библиотека: обложки, аккуратные карточки, сканер, диалоги."""
import hashlib, json, os, subprocess, sys, zipfile
from collections import OrderedDict
from datetime import date, timedelta, datetime
from pathlib import Path
from PySide6.QtCore import (Qt, QThread, Signal, QSize, QRectF, QUrl, QEvent, QTimer,
                            QFileSystemWatcher, QPropertyAnimation, QPoint)
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QImage, QPainter, QPixmap,
                           QKeySequence, QStandardItem, QStandardItemModel, QShortcut, QIcon,
                           QLinearGradient, QPen, QPainterPath, QGuiApplication)
from PySide6.QtWidgets import (QMainWindow, QListView, QStyledItemDelegate, QStyle, QTreeWidget,
                               QStyleOptionViewItem,
                               QTreeWidgetItem, QSplitter, QToolBar, QLineEdit, QComboBox, QWidget,
                               QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QDialog, QDialogButtonBox,
                               QTabWidget, QSpinBox, QDoubleSpinBox, QCheckBox, QFontComboBox,
                               QLabel, QFileDialog, QMessageBox, QMenu, QInputDialog, QProgressBar,
                               QListWidget, QListWidgetItem, QPushButton, QFrame, QToolButton, QTabBar, QAbstractItemView,
                                QGraphicsOpacityEffect)

from common import (S, DATA, DB, COVERS, THEMES, VER, SEMANTIC, ACCENTS, PRESENTATION_FMTS,
                    human, hms, norm, theme)
from formats import ALL_EXTS, open_source, read_meta, FormatError
from library import Library
from reader import Reader
from views import PDF_LOCK
from theming import apply_theme, chrome

EXTS = ALL_EXTS
ROLE = Qt.UserRole + 1
_SESSION_RESTORED = False
GROUP_COLORS = ("#5e6ad2", "#3fb950", "#d29922", "#f85149", "#a371f7", "#58a6ff")
HOME_TAB, LIB_TAB = 0, 1
FMT_COLOR = {k: SEMANTIC["dark"]["data." + k] for k in
             ("pdf", "epub", "fb2", "djvu", "docx", "mobi", "azw3", "txt",
              "pptx", "odp", "ppt", "pps", "ppsx", "otp")}


def save_cover(bid, data):
    if not data:
        return False
    img = QImage.fromData(data)
    if img.isNull():
        return False
    img = img.scaled(340, 510, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return bool(opaque(img).save(str(COVERS / f"{bid}.png"), "PNG"))


def opaque(img, paper="#ffffff"):
    """Обложка без прозрачности: рисуем на подложке цвета бумаги страницы."""
    if img.isNull() or img.format() == QImage.Format_RGB32:
        return img
    out = QImage(img.size(), QImage.Format_RGB32)
    out.fill(QColor(paper))
    p = QPainter(out)
    p.drawImage(0, 0, img)
    p.end()
    return out


class Scanner(QThread):
    found = Signal(dict)
    progress = Signal(str, int, int)
    done = Signal(int)

    def __init__(self, folders, known, hashes=None):
        super().__init__()
        self.folders, self.known, self._stop = folders, known, False
        self.hashes = hashes or {}

    def stop(self): self._stop = True

    @staticmethod
    def _fhash(path, st):
        h = hashlib.sha1(str(st.st_size).encode())
        with open(path, "rb") as f:
            h.update(f.read(65536))
            if st.st_size > 131072:
                f.seek(-65536, os.SEEK_END)
                h.update(f.read(65536))
        return h.hexdigest()

    def run(self):
        files = []
        for f in self.folders:
            root = Path(f)
            if not root.is_dir():
                continue
            for dirpath, dirnames, names in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                if self._stop:
                    break
                for n in names:
                    p = Path(dirpath) / n
                    if p.suffix.lower() not in EXTS:
                        continue
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    k = self.known.get(norm(p))
                    if k and abs(k[1] - st.st_mtime) < 2 and k[0] == st.st_size:
                        continue
                    files.append((p, st))
        n = 0
        seen = set()
        for i, (p, st) in enumerate(files):
            if self._stop:
                break
            self.progress.emit(p.name, i + 1, len(files))
            try:
                fh = self._fhash(p, st)
            except OSError:
                continue
            owner = self.hashes.get(fh)
            if owner and owner != norm(p):
                continue
            if fh in seen:
                continue
            seen.add(fh)
            try:
                with PDF_LOCK:
                    m, fmt = read_meta(str(p))
            except Exception:
                continue
            self.found.emit(dict(path=str(p), fmt=fmt, title=m.title or p.stem,
                                 author="; ".join(a for a in m.authors if a), series=m.series, seq=m.seq,
                                 lang=m.lang, annotation=m.annotation[:2000], genres="; ".join(m.genres[:8]),
                                 size=st.st_size, mtime=st.st_mtime, cover=m.cover, fhash=fh))
            n += 1
        self.done.emit(n)


class CoverWorker(QThread):
    """Догружает обложки для книг, у которых их нет."""
    got = Signal(int)
    finishedAll = Signal()

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs
        self._stop = False

    def stop(self): self._stop = True

    def run(self):
        for bid, path, fmt in self.jobs:
            if self._stop:
                break
            if (COVERS / f"{bid}.png").exists():
                continue
            try:
                with PDF_LOCK:
                    src = open_source(path)
                    data = src.meta.cover
                    if not data and getattr(src, "fixed", False):
                        img = opaque(src.render(0, QSize(340, 480)))
                        if not img.isNull():
                            ok = img.save(str(COVERS / f"{bid}.png"), "PNG")
                            src.close()
                            if ok:
                                self.got.emit(bid)
                            continue
                    src.close()
                if data and save_cover(bid, data):
                    self.got.emit(bid)
            except Exception:
                continue
        self.finishedAll.emit()


class BookDelegate(QStyledItemDelegate):
    """Карточки книг: обложка, статус, прогресс и аккуратная типографика."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = True
        self.hover = None
        self.action_rects = {}
        self._pix = OrderedDict()
        self._scaled = OrderedDict()
        self._miss = set()
        self._theme = S["theme"]
        th = theme(self._theme)
        self._c = chrome(th)
        self._dark = th["dark"]

    def _sync_theme(self):
        if self._theme != S["theme"]:
            self._theme = S["theme"]
            th = theme(self._theme)
            self._c = chrome(th)
            self._dark = th["dark"]
            self._scaled.clear()

    def bust(self, bid=None):
        self._theme = S["theme"]
        th = theme(self._theme)
        self._c = chrome(th)
        self._dark = th["dark"]
        if bid is None:
            self._pix.clear(); self._miss.clear(); self._scaled.clear()
        else:
            self._pix.pop(bid, None); self._miss.discard(bid)
            for k in [k for k in self._scaled if k[0] == bid]:
                self._scaled.pop(k, None)

    def pix(self, bid):
        if bid in self._pix:
            self._pix.move_to_end(bid)
            return self._pix[bid]
        pm = QPixmap(str(COVERS / f"{bid}.png"))
        if pm.isNull():
            pm = QPixmap()
            self._miss.add(bid)
        self._pix[bid] = pm
        while len(self._pix) > 500:
            self._pix.popitem(last=False)
        return pm

    def _card_width(self):
        view = self.parent()
        try:
            avail = view.viewport().width() - 16
        except Exception:
            avail = 0
        if avail < 120:
            return 192
        cols = max(1, avail // 166)
        return max(150, min(240, avail // cols - 8))

    def sizeHint(self, opt, idx):
        if not self.grid:
            try:
                w = self.parent().viewport().width() - 12
            except Exception:
                w = 520
            return QSize(max(280, min(520, w)), 86)
        w = self._card_width()
        return QSize(w, round(w * 1.59))

    def _status_color(self, status):
        roles = {"read": "status.success", "reading": "status.info",
                 "planned": "status.neutral", "new": "accent.default"}
        return QColor(self._c[roles.get(status, "accent.default")])

    def _fmt_color(self, fmt):
        fallback = FMT_COLOR.get(fmt, self._c["text.tertiary"])
        return QColor(self._c.get("data." + fmt, fallback))

    @staticmethod
    def _round(box, r=4):
        path = QPainterPath()
        path.addRoundedRect(box, r, r)
        return path

    @staticmethod
    def _dot(p, x, y, color, diameter=6):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(x, y, diameter, diameter))

    def _draw_actions(self, p, cover):
        c = self._c
        size, gap = 18, 4
        x = cover.right() - (size + gap) * 3 - 6
        y = cover.y() + 7
        f = p.font(); f.setPointSize(10); f.setWeight(QFont.Medium); p.setFont(f)
        for key, glyph in (("read", "▶"), ("fav", "★"), ("info", "i")):
            r = QRectF(x, y, size, size)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 150))
            p.drawEllipse(r)
            p.setPen(QColor(c["text.primary"]))
            p.drawText(r, Qt.AlignCenter, glyph)
            self.action_rects[key] = r
            x += size + gap

    @staticmethod
    def _label_on_cover(p, x, y, text, color, size=8):
        f = p.font(); f.setPointSize(size); f.setWeight(QFont.Medium); p.setFont(f)
        box = QRectF(x, y, 80, 14)
        p.setPen(QColor(0, 0, 0, 150))
        p.drawText(box.translated(1, 1), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.setPen(QColor(color))
        p.drawText(box, Qt.AlignLeft | Qt.AlignVCenter, text)

    def _placeholder(self, p, box, b):
        c = self._c
        col = self._fmt_color(b["fmt"])
        g = QLinearGradient(box.topLeft(), box.bottomRight())
        g.setColorAt(0.0, QColor(c["bg.raised"]))
        g.setColorAt(1.0, QColor(c["bg.panel"]))
        p.setPen(Qt.NoPen)
        p.fillPath(self._round(box), g)
        tint = QColor(col); tint.setAlpha(16 if self._dark else 10)
        p.setBrush(tint)
        p.drawRoundedRect(box, 4, 4)
        # «корешок» и тонкая линия — заглушка похожа на обложку
        spine = QColor(col); spine.setAlpha(60)
        p.setBrush(spine)
        p.drawRoundedRect(QRectF(box.x(), box.y(), 5, box.height()), 2, 2)
        p.setBrush(Qt.NoBrush)  # иначе контур закрасит обложку ещё раз
        p.setPen(QPen(QColor(c["border.strong"]), 1))
        p.drawLine(box.x() + 14, box.y() + 52, box.right() - 14, box.y() + 52)
        p.drawPath(self._round(box))
        title = QColor(c["text.primary"]); title.setAlpha(235)
        p.setPen(title)
        f = p.font(); f.setPointSize(10); f.setWeight(QFont.Medium); p.setFont(f)
        p.drawText(box.adjusted(12, 12, -10, -36), Qt.AlignTop | Qt.TextWordWrap, b["title"][:70])
        p.setPen(QColor(c["text.secondary"]))
        f.setPointSize(8); f.setWeight(QFont.Normal); p.setFont(f)
        p.drawText(box.adjusted(12, 0, -10, -10), Qt.AlignBottom | Qt.AlignLeft, b["fmt"].upper())

    def _cover(self, p, box, b, pm):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._c["shadow"]))
        p.drawRoundedRect(box.adjusted(1, 3, 1, -1), 4, 4)
        if pm.isNull():
            self._placeholder(p, box, b)
        else:
            key = (b["id"], int(box.width()), int(box.height()))
            s = self._scaled.get(key)
            if s is None:
                s = pm.scaled(box.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._scaled[key] = s
                if len(self._scaled) > 600:
                    self._scaled.popitem(last=False)
            x = box.x() + (box.width() - s.width()) / 2
            y = box.y() + (box.height() - s.height()) / 2
            p.setClipPath(self._round(box))
            p.drawPixmap(QRectF(x, y, s.width(), s.height()), s, QRectF(s.rect()))
            p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(self._c["border.strong"]), 1))
        p.drawRoundedRect(box, 4, 4)

    def paint(self, p, opt, idx):
        b = idx.data(ROLE)
        if not isinstance(b, dict):
            return
        self._sync_theme()
        c = self._c
        fg = QColor(c["text.primary"])
        dim = QColor(c["text.secondary"])
        faint = QColor(c["text.tertiary"])
        status = self._status_color(b["status"])
        fmt_col = self._fmt_color(b["fmt"])
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(opt.rect).adjusted(10, 10, -10, -10)
        self.action_rects = {}
        if opt.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen); p.setBrush(QColor(c["bg.selected"]))
            p.drawRoundedRect(QRectF(opt.rect).adjusted(2, 2, -2, -2), 4, 4)
        elif b["id"] == self.hover:
            col = QColor(c["accent.default"]); col.setAlpha(110)
            p.setPen(QPen(col, 1)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(opt.rect).adjusted(2, 2, -2, -2), 4, 4)
        pm = self.pix(b["id"])

        if self.grid:
            cover = QRectF(r.x(), r.y(), r.width(), r.height() * 0.655)
            self._cover(p, cover, b, pm)
            if b["id"] == self.hover:
                self._draw_actions(p, cover)
            labels = {"reading": "ЧИТАЮ", "read": "ПРОЧИТАНО", "planned": "ПЛАН"}
            label = labels.get(b["status"])
            if label:
                self._dot(p, cover.x() + 10, cover.y() + 10, status)
                self._label_on_cover(p, cover.x() + 20, cover.y() + 3, label, c["text.primary"])
            if b["favorite"] and b["id"] != self.hover:
                star = QRectF(cover.right() - 25, cover.y() + 7, 18, 18)
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 110))
                p.drawEllipse(star)
                p.setPen(QColor(c["status.warning"]))
                f = p.font(); f.setPointSize(10); f.setWeight(QFont.Medium); p.setFont(f)
                p.drawText(star, Qt.AlignCenter, "★")

            f = p.font(); f.setPointSize(11); f.setWeight(QFont.Medium); p.setFont(f)
            p.setPen(fg)
            fm = p.fontMetrics()
            line1 = fm.elidedText(b["title"], Qt.ElideRight, int(r.width()))
            ty = cover.bottom() + 10
            p.drawText(QRectF(r.x(), ty, r.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, line1)
            rest = b["title"][max(0, len(line1) - 1):] if line1.endswith("…") else ""
            if rest:
                line2 = fm.elidedText(rest, Qt.ElideRight, int(r.width()))
                p.drawText(QRectF(r.x(), ty + 15, r.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, line2)
                ty += 15
            f.setPointSize(9); f.setWeight(QFont.Normal); p.setFont(f); p.setPen(dim)
            p.drawText(QRectF(r.x(), ty + 17, r.width(), 15), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(b["author"] or "Автор не указан", Qt.ElideRight, int(r.width())))
            my = cover.bottom() + 66
            self._dot(p, r.x() + 1, my + 4, fmt_col, 5)
            p.setPen(faint); f.setPointSize(8); p.setFont(f)
            p.drawText(QRectF(r.x() + 11, my, r.width() - 44, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{b['fmt'].upper()} · {human(b['size'])}")
            p.setPen(status); f.setPointSize(9); f.setWeight(QFont.Medium); p.setFont(f)
            p.drawText(QRectF(r.right() - 42, my, 42, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{b['progress'] * 100:.0f}%")
            bar = QRectF(r.x(), r.bottom() - 6, r.width(), 2)
        else:
            cw, chh = 50.0, r.height()
            box = QRectF(r.x(), r.y(), cw, chh)
            self._cover(p, box, b, pm)
            tx = r.x() + cw + 12
            self._dot(p, tx, r.y() + 9, status)
            title_x = tx + 12
            if b["favorite"]:
                p.setPen(QColor(c["status.warning"]))
                f = p.font(); f.setPointSize(10); f.setWeight(QFont.Medium); p.setFont(f)
                p.drawText(QRectF(tx + 8, r.y() + 1, 16, 18), Qt.AlignLeft | Qt.AlignVCenter, "★")
                title_x += 18
            tw = r.right() - 126 - title_x
            f = p.font(); f.setPointSize(11); f.setWeight(QFont.Medium); p.setFont(f); p.setPen(fg)
            p.drawText(QRectF(title_x, r.y() + 1, tw, 20), Qt.AlignVCenter,
                       p.fontMetrics().elidedText(b["title"], Qt.ElideRight, int(tw)))
            f.setPointSize(9); f.setWeight(QFont.Normal); p.setFont(f); p.setPen(dim)
            sub = (b["author"] or "Автор не указан") + (" · " + b["series"] if b["series"] else "")
            p.drawText(QRectF(title_x, r.y() + 22, tw, 16), Qt.AlignVCenter,
                       p.fontMetrics().elidedText(sub, Qt.ElideRight, int(tw)))
            rx = r.right() - 118
            self._dot(p, rx, r.y() + 7, fmt_col, 5)
            p.setPen(faint); f.setPointSize(8); p.setFont(f)
            p.drawText(QRectF(rx + 10, r.y() + 5, 48, 18), Qt.AlignLeft | Qt.AlignVCenter, b["fmt"].upper())
            p.setPen(dim); f.setPointSize(9); p.setFont(f)
            p.drawText(QRectF(rx + 58, r.y() + 5, 54, 18), Qt.AlignRight | Qt.AlignVCenter, human(b["size"]))
            p.setPen(status); f.setPointSize(9); f.setWeight(QFont.Medium); p.setFont(f)
            p.drawText(QRectF(rx, r.y() + 27, 118, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{b['progress'] * 100:.0f}%")
            bar = QRectF(tx, r.bottom() - 6, r.width() - (tx - r.x()), 2)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["bg.subtle"]))
        p.drawRoundedRect(bar, 1, 1)
        p.setBrush(status)
        p.drawRoundedRect(QRectF(bar.x(), bar.y(),
                                 max(2.0, bar.width() * min(1.0, b["progress"])),
                                 bar.height()), 1, 1)
        p.restore()


SCHEMA_UI = [
    ("Чтение", [
        ("font_family", "Шрифт", "font"), ("font_size", "Кегль, pt", "int", 8, 40),
        ("bold", "Полужирный", "bool"), ("line_spacing", "Межстрочный, %", "int", 95, 200),
        ("indent", "Абзацный отступ", "int", 0, 56), ("para_space", "Отступ между абзацами", "int", 0, 30),
        ("align", "Выключка", "choice", ["justify", "left"]),
        ("margin", "Поля", "int", 6, 110), ("gap", "Зазор колонок", "int", 8, 90),
        ("columns", "Колонок", "choice", [1, 2]), ("mode", "Режим", "choice", ["paged", "scroll"]),
        ("brightness", "Яркость", "float", 0.3, 1.0),
        ("hyphenate", "Мягкие переносы (текстовые книги)", "bool"),
        ("office_pdf", "Office: точный вид через PDF (1:1)", "bool"),
        ("office_cache_days", "Хранить кэш PDF, дней", "int", 1, 365),
        ("office_cache_mb", "Лимит кэша PDF, МБ", "int", 50, 4096),
    ]),
    ("PDF и сканы", [
        ("pdf_fit", "Подгонка", "choice", ["width", "page", "custom"]),
        ("pdf_zoom", "Масштаб, %", "int", 25, 600),
        ("pdf_crop", "Обрезать поля скана", "bool"),
        ("pdf_invert", "Инверсия в тёмной теме", "bool"),
        ("pdf_gap", "Зазор между страницами", "int", 0, 60),
        ("pdf_shadow", "Тень страницы", "bool"),
        ("render_scale", "Резкость рендера", "choice", [1.0, 1.5, 2.0]),
    ]),
    ("Тема", [("theme", "Тема чтения", "choice", list(THEMES)),
              ("accent", "Акцентный цвет", "choice", list(ACCENTS))]),
    ("Управление", [
        ("tap_zones", "Тап-зоны", "bool"), ("wheel_pages", "Колесо листает страницы", "bool"),
        ("autoscroll", "Скорость автопрокрутки", "int", 5, 200),
        ("tune_visible", "Панель настройки при открытии", "bool"),
    ]),
    ("Сервисы", [
        ("tts_voice", "Голос TTS", "voice"), ("tts_rate", "Скорость", "float", -1.0, 1.0),
        ("tts_pitch", "Тон", "float", -1.0, 1.0), ("tts_vol", "Громкость", "float", 0.0, 1.0),
        ("tts_follow", "Автоперелистывание при озвучке", "bool"),
        ("dict_paths", "Папки словарей StarDict", "paths"),
        ("webdav_url", "WebDAV URL", "text"),
        ("webdav_user", "WebDAV пользователь", "text"),
        ("webdav_password", "WebDAV пароль", "text"),
        ("webdav_auto", "Синхронизировать при закрытии", "bool"),
        ("update_url", "URL релизов (GitHub API)", "text"),
        ("update_auto", "Проверять обновления при запуске", "bool"),
        ("show_network", "Показывать сетевые функции", "bool"),
    ]),
    ("Библиотека", [
        ("folders", "Папки сканирования", "paths"), ("scan_on_start", "Сканировать при запуске", "bool"),
        ("save_per_book", "Запоминать настройки для каждой книги", "bool"),
    ]),
]


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None, live=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setAccessibleName("Настройки приложения")
        g = self.screen().availableGeometry()
        self.resize(min(600, int(g.width() * 0.85)), min(660, int(g.height() * 0.85)))
        self.s, self.live = settings, live
        lay = QVBoxLayout(self)
        self.tabs = tabs = QTabWidget(); lay.addWidget(tabs)
        for title, rows in SCHEMA_UI:
            w = QWidget(); fl = QFormLayout(w); fl.setSpacing(9)
            for row in rows:
                key, label, kind = row[0], row[1], row[2]
                val = self.s.get(key)
                if kind == "int":
                    e = QSpinBox(); e.setRange(row[3], row[4]); e.setValue(int(val))
                    e.valueChanged.connect(lambda v, k=key: self.set(k, v))
                elif kind == "float":
                    e = QDoubleSpinBox(); e.setRange(row[3], row[4]); e.setSingleStep(0.05)
                    e.setValue(float(val))
                    e.valueChanged.connect(lambda v, k=key: self.set(k, v))
                elif kind == "bool":
                    e = QCheckBox(); e.setChecked(bool(val))
                    e.toggled.connect(lambda v, k=key: self.set(k, v))
                elif kind == "choice":
                    e = QComboBox(); e.addItems([str(x) for x in row[3]])
                    e.setCurrentText(str(val))
                    e.currentTextChanged.connect(
                        lambda v, k=key, o=row[3]: self.set(k, type(o[0])(v) if isinstance(o[0], (int, float)) else v))
                elif kind == "font":
                    e = QFontComboBox(); e.setCurrentFont(QFont(val or QFont().family()))
                    e.currentFontChanged.connect(lambda f, k=key: self.set(k, f.family()))
                elif kind == "voice":
                    e = QComboBox(); e.addItem("")
                    try:
                        from services import Tts
                        e.addItems(Tts().voices())
                    except Exception:
                        pass
                    e.setCurrentText(str(val)); e.currentTextChanged.connect(lambda v, k=key: self.set(k, v))
                elif kind == "paths":
                    box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0)
                    lst = QListWidget(); lst.setMaximumHeight(110); lst.addItems(list(val or []))
                    bw = QWidget(); bv = QVBoxLayout(bw)
                    add = QPushButton("+"); rem = QPushButton("−")
                    bv.addWidget(add); bv.addWidget(rem); bv.addStretch()
                    h.addWidget(lst); h.addWidget(bw)
                    def do_add(_=False, l=lst, k=key):
                        d = QFileDialog.getExistingDirectory(self, "Папка")
                        if d:
                            l.addItem(d); self.set(k, [l.item(i).text() for i in range(l.count())])
                    def do_rem(_=False, l=lst, k=key):
                        for it in l.selectedItems():
                            l.takeItem(l.row(it))
                        self.set(k, [l.item(i).text() for i in range(l.count())])
                    add.clicked.connect(do_add); rem.clicked.connect(do_rem)
                    e = box
                else:
                    e = QLineEdit(str(val)); e.textChanged.connect(lambda v, k=key: self.set(k, v))
                fl.addRow(label, e)
            tabs.addTab(w, title)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Ok).setDefault(True)
        lay.addWidget(bb)
        QTimer.singleShot(0, lambda: self.tabs.widget(0).setFocus())

    def set(self, k, v):
        self.s[k] = v
        if self.live:
            self.live({k: v})


class FilePropertiesDialog(QDialog):
    """Свойства файла книги: путь, размер, даты и метаданные, как в Windows."""

    def __init__(self, lib, bid, parent=None):
        super().__init__(parent)
        self.lib, self.bid = lib, bid
        b = dict(lib.book(bid) or {})
        self.setWindowTitle("Свойства файла")
        self.setAccessibleName("Свойства файла")
        g = self.screen().availableGeometry()
        self.resize(min(620, int(g.width() * 0.85)), min(520, int(g.height() * 0.85)))

        lay = QVBoxLayout(self)
        tabs = QTabWidget()

        path = b.get("path") or ""
        p = Path(path)
        st = None
        if path:
            try:
                st = p.stat() if p.exists() else None
            except OSError:
                st = None

        def stamp(ts):
            if not ts:
                return "—"
            try:
                return datetime.fromtimestamp(float(ts)).strftime("%d.%m.%Y %H:%M:%S")
            except (ValueError, OSError, OverflowError):
                return "—"

        def row(form, label, value, selectable=False):
            w = QLabel(str(value) if value not in (None, "") else "—")
            w.setWordWrap(True)
            if selectable:
                w.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(label + ":", w)
            return w

        general = QWidget(); form = QFormLayout(general)
        row(form, "Название", b.get("title"))
        row(form, "Автор", b.get("author"))
        row(form, "Формат", (b.get("fmt") or "").upper())
        row(form, "Путь", path, True)
        row(form, "Папка", str(p.parent) if path else "—", True)
        row(form, "Имя файла", p.name if path else "—", True)
        if st is None:
            row(form, "Файл на диске", "Недоступен")
        else:
            row(form, "Размер на диске", human(st.st_size))
            row(form, "Создан", stamp(st.st_ctime))
            row(form, "Изменён", stamp(st.st_mtime))
            row(form, "Последний доступ", stamp(st.st_atime))
            try:
                row(form, "Открыт для записи", "да" if os.access(path, os.W_OK) else "нет")
            except OSError:
                pass
            try:
                row(form, "Идентификатор", Scanner._fhash(p, st)[:16])
            except OSError:
                pass
        row(form, "Размер в библиотеке", human(b.get("size") or 0))
        row(form, "Добавлен в библиотеку", stamp(b.get("added")))
        row(form, "Статус", b.get("status"))
        row(form, "Прогресс", f"{(b.get('progress') or 0) * 100:.1f}%")
        row(form, "Время чтения", hms(b.get("seconds") or 0))
        tabs.addTab(general, "Общие")

        meta_tab = QWidget(); meta_form = QFormLayout(meta_tab)
        meta, _fmt = None, ""
        if path and p.exists():
            try:
                meta, _fmt = read_meta(path)
            except Exception:
                meta = None
        if meta:
            row(meta_form, "Заголовок", meta.title)
            row(meta_form, "Авторы", "; ".join(a for a in meta.authors if a))
            row(meta_form, "Серия", meta.series)
            row(meta_form, "Номер в серии", meta.seq or "")
            row(meta_form, "Язык", meta.lang)
            row(meta_form, "Жанры", "; ".join(meta.genres))
            row(meta_form, "Аннотация", meta.annotation)
        else:
            row(meta_form, "Метаданные", "Не удалось прочитать")
        tabs.addTab(meta_tab, "Метаданные")
        lay.addWidget(tabs)

        buttons = QHBoxLayout()
        open_folder = QPushButton("Открыть папку")
        open_folder.clicked.connect(self.open_folder)
        copy_path = QPushButton("Копировать путь")
        copy_path.clicked.connect(self.copy_path)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        close.setDefault(True)
        buttons.addWidget(open_folder); buttons.addWidget(copy_path); buttons.addStretch(1)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        self._path = path

    def open_folder(self):
        if self._path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._path).parent)))

    def copy_path(self):
        if self._path:
            QGuiApplication.clipboard().setText(self._path)
            win = self.window()
            if win is not None and hasattr(win, "notify"):
                win.notify("Путь скопирован")
            else:
                pass


class InfoDialog(QDialog):
    """Карточка книги: редактируемые метаданные, метки, своя обложка."""

    def __init__(self, lib, bid, parent=None):
        super().__init__(parent)
        self.lib, self.bid = lib, bid
        b = lib.book(bid)
        self.setWindowTitle("О книге")
        self.setAccessibleName("Сведения о книге")
        g = self.screen().availableGeometry()
        self.resize(min(640, int(g.width() * 0.85)), min(600, int(g.height() * 0.85)))
        self._cover_data = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout(); lay.addLayout(top)
        self.cov = QLabel(); pm = QPixmap(str(COVERS / f"{bid}.png"))
        if not pm.isNull():
            self.cov.setPixmap(pm.scaled(160, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(self.cov)
        form = QFormLayout(); top.addLayout(form, 1)
        self.f_title = QLineEdit(b["title"] or "")
        self.f_author = QLineEdit(b["author"] or "")
        self.f_series = QLineEdit(b["series"] or "")
        self.f_seq = QLineEdit(str(b["seq"] or ""))
        self.f_lang = QLineEdit(b["lang"] or "")
        self.f_genres = QLineEdit(b["genres"] or "")
        for label, w in (("Название", self.f_title), ("Автор", self.f_author),
                         ("Серия", self.f_series), ("Номер в серии", self.f_seq),
                         ("Язык", self.f_lang), ("Жанры", self.f_genres)):
            form.addRow(label + ":", w)
        self.f_ann = QLineEdit(b["annotation"] or "")
        self.f_ann.setPlaceholderText("Аннотация")
        form.addRow("Аннотация:", self.f_ann)
        info = QLabel(f"<b>Формат:</b> {b['fmt'].upper()} · {human(b['size'])}<br>"
                      f"<b>Прогресс:</b> {b['progress'] * 100:.1f}%<br>"
                      f"<b>Чтение:</b> {hms(b['seconds'])}<br>"
                      f"<b>Путь:</b> {b['path']}")
        info.setWordWrap(True); lay.addWidget(info)
        row = QHBoxLayout()
        self.status = QComboBox(); self.status.addItems(["new", "reading", "read", "planned"])
        self.status.setCurrentText(b["status"])
        self.status.currentTextChanged.connect(lambda v: lib.set_field(bid, status=v))
        self.fav = QCheckBox("Избранное"); self.fav.setChecked(bool(b["favorite"]))
        self.fav.toggled.connect(lambda v: lib.set_field(bid, favorite=int(v)))
        row.addWidget(QLabel("Статус:")); row.addWidget(self.status); row.addWidget(self.fav); row.addStretch()
        lay.addLayout(row)

        side = QHBoxLayout()
        cbox = QVBoxLayout(); cbox.addWidget(QLabel("Коллекции:"))
        self.colls = QListWidget(); self.colls.setMaximumHeight(110)
        have = lib.book_colls(bid)
        for c in lib.colls():
            it = QListWidgetItem(c["name"]); it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if c["id"] in have else Qt.Unchecked)
            it.setData(Qt.UserRole, c["id"]); self.colls.addItem(it)
        self.colls.itemChanged.connect(self.coll_changed)
        cbox.addWidget(self.colls)
        tbox = QVBoxLayout(); tbox.addWidget(QLabel("Метки:"))
        self.tags = QListWidget(); self.tags.setMaximumHeight(110)
        have_tags = lib.book_tags(bid)
        for t in lib.tags():
            it = QListWidgetItem(t["name"]); it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if t["id"] in have_tags else Qt.Unchecked)
            it.setData(Qt.UserRole, t["id"]); self.tags.addItem(it)
        self.tags.itemChanged.connect(self.tag_changed)
        tbox.addWidget(self.tags)
        side.addLayout(cbox); side.addLayout(tbox)
        lay.addLayout(side)

        newtag = QPushButton("Новая метка…"); newtag.clicked.connect(self.new_tag)
        lay.addWidget(newtag, 0, Qt.AlignLeft)
        cover = QPushButton("Загрузить свою обложку…"); cover.clicked.connect(self.pick_cover)
        lay.addWidget(cover, 0, Qt.AlignLeft)
        bb = QDialogButtonBox()
        bb.addButton("Сохранить", QDialogButtonBox.AcceptRole)
        bb.addButton("Закрыть", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.save); bb.rejected.connect(self.reject)
        for button in bb.buttons():
            if button.text() == "Сохранить":
                button.setDefault(True)
                break
        lay.addWidget(bb)
        QTimer.singleShot(0, self.f_title.setFocus)

    def coll_changed(self, it):
        cid = it.data(Qt.UserRole)
        if it.checkState() == Qt.Checked:
            self.lib.coll_add(cid, self.bid)
        else:
            self.lib.coll_del(cid, self.bid)

    def tag_changed(self, it):
        self.lib.tag_book(it.data(Qt.UserRole), self.bid, it.checkState() == Qt.Checked)

    def new_tag(self):
        name, ok = QInputDialog.getText(self, "Метка", "Название метки:")
        if ok and name.strip():
            tid = self.lib.new_tag(name.strip())
            it = QListWidgetItem(name.strip())
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked); it.setData(Qt.UserRole, tid)
            self.tags.addItem(it)
            self.lib.tag_book(tid, self.bid, True)

    def pick_cover(self):
        p, _ = QFileDialog.getOpenFileName(self, "Обложка книги", "", "Изображения (*.png *.jpg *.jpeg *.webp)")
        if not p:
            return
        try:
            data = open(p, "rb").read()
            if not QImage.fromData(data).isNull():
                self._cover_data = data
                pm = QPixmap.fromImage(QImage.fromData(data))
                self.cov.setPixmap(pm.scaled(160, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            pass

    def save(self):
        try:
            seq = float(self.f_seq.text().replace(",", ".")) if self.f_seq.text().strip() else 0.0
        except ValueError:
            seq = 0.0
        self.lib.set_meta(self.bid, title=self.f_title.text().strip(),
                          author=self.f_author.text().strip(), series=self.f_series.text().strip(),
                          seq=seq, lang=self.f_lang.text().strip(), genres=self.f_genres.text().strip(),
                          annotation=self.f_ann.text().strip())
        if self._cover_data:
            save_cover(self.bid, self._cover_data)
        self.accept()


class StatsHeat(QWidget):
    """Кликабельная тепловая карта чтения."""
    clicked = Signal(str)

    def __init__(self, days, weeks=13, parent=None):
        super().__init__(parent)
        self.days = days
        self.n = weeks * 7
        self.setMinimumSize(14 * weeks + 4, 7 * 14 + 4)
        self.setMouseTracking(True)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = chrome(theme(S["theme"]))
        side, step = 11, 14
        today = date.today()
        for i in range(self.n):
            d = today - timedelta(days=self.n - 1 - i)
            secs = float(self.days.get(d.isoformat(), 0) or 0)
            col = QColor(c["accent.default"] if secs > 0 else c["bg.subtle"])
            if secs > 0:
                col.setAlpha(min(255, 90 + int(min(1.0, secs / 3600.0) * 165)))
            p.setPen(Qt.NoPen); p.setBrush(col)
            p.drawRoundedRect(QRectF((i // 7) * step, (i % 7) * step, side, side), 3, 3)
        p.end()

    def mousePressEvent(self, e):
        col = int(e.position().x() // 14)
        row = int(e.position().y() // 14)
        i = col * 7 + row
        if 0 <= i < self.n:
            day = date.today() - timedelta(days=self.n - 1 - i)
            self.clicked.emit(day.isoformat())


class StatsDialog(QDialog):
    def __init__(self, lib, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Статистика чтения")
        self.setAccessibleName("Статистика чтения")
        g = self.screen().availableGeometry()
        self.resize(min(460, int(g.width() * 0.85)), min(300, int(g.height() * 0.85)))
        rows = lib.stats()
        days = {r["day"]: (r["s"] or 0) for r in rows}
        self.days = days
        total = lib.q("SELECT SUM(seconds) s FROM books")[0]["s"] or 0
        pages = sum(int(r["p"] or 0) for r in rows)
        streak = 0
        d = date.today()
        while days.get(d.isoformat(), 0) > 0:
            streak += 1; d -= timedelta(days=1)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<h3>Статистика чтения</h3>"))
        lay.addWidget(QLabel(f"Всего времени: <b>{hms(total)}</b> · Страниц: <b>{pages}</b> · "
                             f"Серия дней: <b>{streak}</b>"))
        top = QHBoxLayout()
        top.addWidget(QLabel("Период:"))
        self.period = QComboBox()
        for text, weeks in (("7 дней", 1), ("30 дней", 5), ("90 дней", 13)):
            self.period.addItem(text, weeks)
        self.period.setCurrentIndex(2)
        top.addWidget(self.period)
        top.addWidget(QLabel("Цель, мин/день:"))
        self.goal = QSpinBox(); self.goal.setRange(0, 1440)
        self.goal.setValue(int(S.get("daily_goal", 0)))
        top.addWidget(self.goal)
        lay.addLayout(top)
        self.goalbar = QProgressBar(); self.goalbar.setTextVisible(True)
        lay.addWidget(self.goalbar)
        self.detail = QLabel("Нажми на день, чтобы увидеть детали")
        lay.addWidget(self.detail)
        self.heat = StatsHeat(days, self.period.currentData(), self)
        lay.addWidget(self.heat)
        if rows:
            best = max(rows, key=lambda r: r["s"] or 0)
            lay.addWidget(QLabel(f"Самый продуктивный день: <b>{best['day']}</b> — {hms(best['s'])}"))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject); bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self.period.currentIndexChanged.connect(self.rebuild_heat)
        self.goal.valueChanged.connect(self.save_goal)
        self.heat.clicked.connect(self.show_day)
        self.update_goal()
        QTimer.singleShot(0, self.period.setFocus)

    def rebuild_heat(self):
        lay = self.layout()
        lay.removeWidget(self.heat)
        self.heat.deleteLater()
        self.heat = StatsHeat(self.days, self.period.currentData(), self)
        self.heat.clicked.connect(self.show_day)
        lay.insertWidget(lay.count() - 1, self.heat)

    def save_goal(self, value):
        S["daily_goal"] = int(value)
        S.save()
        self.update_goal()

    def update_goal(self):
        goal = self.goal.value()
        today = int(self.days.get(date.today().isoformat(), 0) or 0)
        self.goalbar.setVisible(goal > 0)
        if goal > 0:
            limit = goal * 60
            self.goalbar.setRange(0, limit)
            self.goalbar.setValue(min(today, limit))
            self.goalbar.setFormat(f"{hms(today)} / {hms(limit)}")

    def show_day(self, day):
        secs = int(self.days.get(day, 0) or 0)
        goal = self.goal.value() * 60
        extra = ""
        if goal:
            extra = f" · {'цель выполнена' if secs >= goal else f'до цели {hms(goal - secs)}'}"
        self.detail.setText(f"<b>{day}</b>: {hms(secs)}{extra}")


class OpdsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("OPDS-каталоги")
        self.setAccessibleName("Каталоги OPDS")
        g = self.screen().availableGeometry()
        self.resize(min(820, int(g.width() * 0.85)), min(520, int(g.height() * 0.85)))
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.cats = QListWidget()
        self.cats.itemClicked.connect(self.load_catalog)
        add = QPushButton("Добавить каталог…"); add.clicked.connect(self.add_catalog)
        rem = QPushButton("Удалить"); rem.clicked.connect(self.remove_catalog)
        left.addWidget(QLabel("Каталоги:")); left.addWidget(self.cats, 1)
        left.addWidget(add); left.addWidget(rem)
        right = QVBoxLayout()
        self.entries = QListWidget()
        self.entries.itemDoubleClicked.connect(self.download)
        self.entries.itemActivated.connect(self.download)
        self.info = QLabel("Выбери каталог"); self.info.setWordWrap(True)
        down = QPushButton("Скачать в библиотеку"); down.clicked.connect(self.download)
        right.addWidget(self.entries, 1); right.addWidget(self.info); right.addWidget(down)
        root.addLayout(left, 1); root.addLayout(right, 2)
        self.reload_catalogs()
        QTimer.singleShot(0, self.cats.setFocus)

    def reload_catalogs(self):
        self.cats.clear()
        for cat in S.get("opds", []):
            it = QListWidgetItem(cat["name"])
            it.setData(Qt.UserRole, cat)
            self.cats.addItem(it)

    def add_catalog(self):
        name, ok = QInputDialog.getText(self, "OPDS", "Название каталога:")
        if not ok or not name.strip():
            return
        url, ok = QInputDialog.getText(self, "OPDS", "URL фида (Atom):")
        if not ok or not url.strip():
            return
        S["opds"] = [c for c in S.get("opds", []) if c["name"] != name.strip()]
        S["opds"].append(dict(name=name.strip(), url=url.strip()))
        S.save(); self.reload_catalogs()

    def remove_catalog(self):
        it = self.cats.currentItem()
        if not it:
            return
        cat = it.data(Qt.UserRole)
        S["opds"] = [c for c in S.get("opds", []) if c["url"] != cat["url"]]
        S.save(); self.reload_catalogs()

    def load_catalog(self, it):
        from services import Opds
        cat = it.data(Qt.UserRole)
        try:
            entries, nxt = Opds(cat["url"]).feed()
            self.entries.clear()
            for entry in entries:
                label = entry["title"] or "(без названия)"
                if entry["author"]:
                    label += f" — {entry['author']}"
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, entry)
                self.entries.addItem(item)
            self.info.setText(f"Книг: {len(entries)}" + (" · есть следующая страница" if nxt else ""))
        except Exception as e:
            self.info.setText(f"Ошибка каталога: {type(e).__name__}: {e}")

    def download(self):
        from urllib.parse import urlparse
        from services import Opds
        it = self.entries.currentItem()
        if not it:
            return
        entry = it.data(Qt.UserRole)
        links = entry.get("links", {})
        href = next((v for k, v in links.items() if "acquisition" in k), "")
        if not href:
            href = next((v for k, v in links.items() if v), "")
        if not href:
            self.info.setText("У книги нет ссылки на скачивание")
            return
        name = Path(urlparse(href).path).name or "book.epub"
        if Path(name).suffix.lower() not in ALL_EXTS:
            name += ".epub"
        dest = DATA / "opds" / name
        try:
            Opds(href).download(href, dest)
            self.win.import_path(str(dest))
            self.info.setText(f"Скачано: {name}")
        except Exception as e:
            self.info.setText(f"Ошибка скачивания: {type(e).__name__}: {e}")


class AllNotesDialog(QDialog):
    def __init__(self, lib, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle("Все заметки")
        self.setAccessibleName("Все заметки")
        g = self.screen().availableGeometry()
        self.resize(min(760, int(g.width() * 0.85)), min(480, int(g.height() * 0.85)))
        lay = QVBoxLayout(self)
        self.q = QLineEdit(); self.q.setPlaceholderText("Поиск по заметкам, цитатам и книгам…")
        self.q.textChanged.connect(self.reload)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.open_current)
        lay.addWidget(self.q); lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Close)
        bb.accepted.connect(self.open_current); bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Open).setDefault(True)
        lay.addWidget(bb)
        self.reload()
        QTimer.singleShot(0, self.q.setFocus)

    def reload(self):
        query = self.q.text().strip().lower()
        rows = self.lib.q("SELECT n.*, b.title btitle FROM notes n "
                          "JOIN books b ON b.id=n.book ORDER BY n.created DESC")
        self.list.clear()
        for r in rows:
            hay = f"{r['note'] or ''} {r['text'] or ''} {r['btitle'] or ''}".lower()
            if query and query not in hay:
                continue
            it = QListWidgetItem(f"{r['btitle'] or 'Без названия'}\n"
                                 f"{(r['text'] or '')[:90]}\n{(r['note'] or '')[:120]}")
            it.setData(Qt.UserRole, dict(r))
            self.list.addItem(it)

    def open_current(self):
        it = self.list.currentItem()
        if not it:
            return
        r = it.data(Qt.UserRole)
        self.accept()
        win = self.parent()
        win.open_book(r["book"])
        QTimer.singleShot(150, lambda: self.focus_note(win.reader, r["id"]))

    @staticmethod
    def focus_note(reader, nid):
        if not reader:
            return
        reader.open_panel(2)
        for i in range(reader.notes.count()):
            it = reader.notes.item(i)
            data = it.data(Qt.UserRole)
            if data and data.get("id") == nid:
                reader.notes.setCurrentItem(it)
                reader.note_click(it)
                break


class HomePage(QWidget):
    """Главный экран: продолжить чтение, недавние книги и цель."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setObjectName("HomePage")
        self.setAccessibleName("Главный экран")
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 22, 30, 22)
        root.setSpacing(18)

        header = QHBoxLayout(); header.setSpacing(8)
        page_title = QLabel("Главная")
        page_title.setObjectName("HomePageTitle")
        page_hint = QLabel("Ваши книги и прогресс чтения")
        page_hint.setObjectName("HomePageHint")
        header.addWidget(page_title); header.addWidget(page_hint, 0, Qt.AlignBottom)
        header.addStretch(1)
        root.addLayout(header)

        title = QLabel("Продолжить чтение")
        title.setObjectName("HomeTitle")
        root.addWidget(title)

        self.cont = QFrame()
        self.cont.setObjectName("ContinueCard")
        ch = QHBoxLayout(self.cont)
        ch.setContentsMargins(18, 16, 18, 16)
        ch.setSpacing(18)
        self.cont_cover = QLabel()
        self.cont_cover.setFixedSize(QSize(80, 114))
        self.cont_cover.setAlignment(Qt.AlignCenter)
        ch.addWidget(self.cont_cover)
        col = QVBoxLayout(); col.setSpacing(5)
        self.cont_label = QLabel()
        self.cont_label.setObjectName("ContinueLabel")
        self.cont_label.setWordWrap(True)
        self.cont_meta = QLabel(); self.cont_meta.setObjectName("ContinueMeta")
        self.cont_bar = QProgressBar(); self.cont_bar.setFixedHeight(4)
        self.cont_bar.setTextVisible(False)
        col.addWidget(self.cont_label); col.addWidget(self.cont_meta); col.addWidget(self.cont_bar)
        ch.addLayout(col, 1)
        btn = QPushButton("Продолжить →"); btn.setObjectName("ContinueBtn")
        btn.clicked.connect(self.win.continue_reading)
        ch.addWidget(btn)
        self.cont.hide()
        root.addWidget(self.cont)

        recent_title = QLabel("Недавние книги")
        recent_title.setObjectName("SectionTitle")
        root.addWidget(recent_title)
        self.recent_host = QWidget()
        self.recent_layout = QGridLayout(self.recent_host)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(12)
        self.recent_layout.setColumnStretch(3, 1)
        self.recent_layout.setRowStretch(2, 1)
        root.addWidget(self.recent_host, 1)

        self.goal = QFrame(); self.goal.setObjectName("GoalCard")
        gl = QHBoxLayout(self.goal); gl.setContentsMargins(14, 12, 14, 12)
        self.goal_label = QLabel(); self.goal_label.setObjectName("HomeSubtle")
        self.goal_bar = QProgressBar(); self.goal_bar.setFixedHeight(3)
        self.goal_bar.setTextVisible(False)
        gl.addWidget(self.goal_label, 1); gl.addWidget(self.goal_bar, 2)
        root.addWidget(self.goal)

        open_btn = QPushButton("Открыть файл…"); open_btn.setObjectName("HomeAction")
        open_btn.clicked.connect(self.win.open_file)
        lib_btn = QPushButton("Перейти в библиотеку"); lib_btn.setObjectName("HomeAction")
        lib_btn.clicked.connect(lambda: self.win.book_tabs.setCurrentIndex(LIB_TAB))
        actions = QHBoxLayout(); actions.addWidget(open_btn); actions.addWidget(lib_btn); actions.addStretch(1)
        root.addLayout(actions)

    def _cover(self, bid, title, w, h):
        """Обложка книги или аккуратная заглушка с первой буквой названия."""
        pm = self.win.deleg.pix(bid)
        if not pm.isNull():
            return pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        from common import ACCENT
        p = QPainter(pm)
        p.fillRect(pm.rect(), QColor("#1d2030"))
        p.setPen(QColor(ACCENT))
        p.drawRect(pm.rect().adjusted(0, 0, -1, -1))
        f = QFont(); f.setPointSize(max(12, h // 4)); f.setWeight(QFont.Medium)
        p.setFont(f); p.drawText(pm.rect(), Qt.AlignCenter, (title or "?")[:1].upper())
        p.end()
        return pm

    def refresh(self):
        lib = self.win.lib
        rows = lib.q("SELECT id,title,author,progress FROM books "
                     "WHERE last_read>0 AND progress>0.001 AND progress<0.995 "
                     "ORDER BY last_read DESC LIMIT 1")
        if not rows:
            self.cont.hide()
        else:
            r = rows[0]
            self.win._continue_id = r["id"]
            name = r["title"] or "Без названия"
            author = f" · {r['author']}" if r["author"] else ""
            self.cont_label.setText(f"{name}{author}")
            self.cont_meta.setText(f"{r['progress'] * 100:.0f}% прочитано")
            self.cont_bar.setRange(0, 100); self.cont_bar.setValue(int(r["progress"] * 100))
            self.cont_cover.setPixmap(self._cover(r["id"], name, 80, 114))
            self.cont.show()

        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        recent = lib.q("SELECT id,title,author,progress FROM books ORDER BY last_read DESC LIMIT 6")
        if not recent:
            hint = QLabel("Здесь появятся недавно открытые книги")
            hint.setObjectName("HomeSubtle")
            self.recent_layout.addWidget(hint, 0, 0)
        for i, r in enumerate(recent):
            title = r["title"] or "Без названия"
            card = QPushButton()
            card.setObjectName("RecentCard")
            card.setToolTip(title + (f" — {r['author']}" if r["author"] else ""))
            card.setIcon(QIcon(self._cover(r["id"], title, 56, 82)))
            card.setIconSize(QSize(56, 82))
            card.setText(f"{title[:24]}\n{r['progress'] * 100:.0f}% прочитано")
            card.clicked.connect(lambda _=False, bid=r["id"]: self.win.open_book(bid))
            self.recent_layout.addWidget(card, i // 3, i % 3)

        goal = int(S.get("daily_goal", 0) or 0)
        today = date.today().isoformat()
        secs = sum((row["s"] or 0) for row in lib.q("SELECT seconds s FROM stats WHERE day=?", (today,)))
        if goal:
            limit = goal * 60
            self.goal_bar.setRange(0, limit)
            self.goal_bar.setValue(min(int(secs), limit))
            self.goal_label.setText(f"Цель на сегодня: {hms(int(secs))} / {hms(limit)}")
            self.goal.show()
        else:
            self.goal_label.setText("Цель чтения не задана — F7 → Сервисы")
            self.goal.hide()


class NavDelegate(QStyledItemDelegate):
    """Аккуратная подсветка дерева навигации: точка роли и акцентная полоса."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = S["theme"]
        th = theme(self._theme)
        self._c = chrome(th)

    def paint(self, p, opt, index):
        if self._theme != S["theme"]:
            self._theme = S["theme"]
            self._c = chrome(theme(self._theme))
        c = self._c
        f = index.data(Qt.UserRole)
        kind = f.get("kind") if isinstance(f, dict) else ""
        colors = {
            "status": c["accent.default"],
            "fav": c["status.warning"],
            "tag": c["data.djvu"],
            "coll": c["data.docx"],
            "smart": c["status.success"],
            "presentations": c["data.pptx"],
            "folder": c["text.tertiary"],
        }
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        view = QStyleOptionViewItem(opt)
        view.rect = opt.rect.adjusted(14, 0, 0, 0)
        super().paint(p, view, index)
        r = QRectF(opt.rect)
        if kind:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(colors.get(kind, c["text.tertiary"])))
            p.drawEllipse(QRectF(r.x() + 4, r.center().y() - 3, 6, 6))
        if opt.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["accent.default"]))
            p.drawRoundedRect(QRectF(r.x() + 1, r.y() + 3, 2, r.height() - 6), 1, 1)
        p.restore()


class Toast(QFrame):
    """Неблокирующее уведомление поверх окна."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAccessibleName("Уведомление")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        lay.addWidget(self.label)
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.anim.setDuration(180)
        self.anim.finished.connect(self._on_anim)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)
        self.hide()

    def notify(self, text):
        self.label.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move(QPoint(max(12, parent.width() - self.width() - 18), 52))
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(2600)

    def _fade_out(self):
        self.anim.stop()
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.start()

    def _on_anim(self):
        if self.effect.opacity() < 0.05:
            self.hide()


class SmartDialog(QDialog):
    def __init__(self, lib, rule=None, parent=None):
        super().__init__(parent)
        rule = rule or {}
        self.setWindowTitle("Умная коллекция"); self.resize(430, 330)
        self.setAccessibleName("Правило умной коллекции")
        lay = QFormLayout(self)

        self.f_name = QLineEdit(rule.get("name", ""))
        self.f_status = QComboBox(); self.f_status.addItem("Любой", "")
        for value, text in (("new", "Не начата"), ("reading", "Читаю"),
                            ("read", "Прочитано"), ("planned", "Планирую")):
            self.f_status.addItem(text, value)
        self.f_fmt = QComboBox(); self.f_fmt.addItem("Любой", "")
        for f in ("pdf", "epub", "fb2", "djvu", "docx", "txt", "mobi", "azw3",
                  "pptx", "odp", "ppt", "pps", "ppsx", "otp"):
            self.f_fmt.addItem(f.upper(), f)
        self.f_tag = QComboBox(); self.f_tag.addItem("Любая", 0)
        for t in lib.tags():
            self.f_tag.addItem(t["name"], t["id"])
        self.f_fav = QCheckBox("Только избранное")
        self.f_days = QSpinBox(); self.f_days.setRange(0, 3650); self.f_days.setSuffix(" дней")
        self.f_min = QDoubleSpinBox(); self.f_min.setRange(0, 1); self.f_min.setSingleStep(0.05)
        self.f_max = QDoubleSpinBox(); self.f_max.setRange(0, 1); self.f_max.setSingleStep(0.05)
        self.f_max.setValue(1)

        self.f_status.setCurrentIndex(max(0, self.f_status.findData(rule.get("status", ""))))
        self.f_fmt.setCurrentIndex(max(0, self.f_fmt.findData(rule.get("fmt", ""))))
        self.f_tag.setCurrentIndex(max(0, self.f_tag.findData(rule.get("tag", 0))))
        self.f_fav.setChecked(bool(rule.get("favorite")))
        self.f_days.setValue(int(rule.get("days", 0)))
        self.f_min.setValue(float(rule.get("min_progress", 0)))
        self.f_max.setValue(float(rule.get("max_progress", 1)))

        for label, w in (("Название", self.f_name), ("Статус", self.f_status), ("Формат", self.f_fmt),
                         ("Метка", self.f_tag), ("Избранное", self.f_fav), ("Добавлено за", self.f_days),
                         ("Прогресс от", self.f_min), ("Прогресс до", self.f_max)):
            lay.addRow(label + ":", w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Ok).setDefault(True)
        lay.addRow(bb)
        QTimer.singleShot(0, self.f_name.setFocus)

    def values(self):
        return dict(name=self.f_name.text().strip(), status=self.f_status.currentData(),
                    fmt=self.f_fmt.currentData(), tag=self.f_tag.currentData(),
                    favorite=self.f_fav.isChecked(), days=self.f_days.value(),
                    min_progress=self.f_min.value(), max_progress=self.f_max.value())


class CommandPalette(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Команды"); self.setMinimumWidth(540)
        self.setAccessibleName("Палитра команд")
        lay = QVBoxLayout(self)
        self.q = QLineEdit(); self.q.setPlaceholderText("Книга или команда…")
        self.list = QListWidget()
        lay.addWidget(self.q); lay.addWidget(self.list)
        self.q.textChanged.connect(self.fill)
        self.q.returnPressed.connect(self.run_current)
        QTimer.singleShot(0, self.q.setFocus)
        self.list.itemActivated.connect(self.run)
        self._items = []

    def add(self, label, fn):
        self._items.append((label, fn))

    def fill(self, text=""):
        self.list.clear()
        q = text.strip().lower()
        for label, fn in self._items:
            if q and q not in label.lower():
                continue
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, fn)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _fire(self, it):
        fn = it.data(Qt.UserRole)
        self.accept()
        if fn:
            fn()

    def run_current(self):
        it = self.list.currentItem()
        if it:
            self._fire(it)

    def run(self, it):
        self._fire(it)


class Win(QMainWindow):
    def __init__(self):
        super().__init__()
        apply_theme(S["theme"], force=True)
        self.lib = Library()
        if not self.lib.integrity_ok:
            msg = "База данных была повреждена и пересоздана"
            if self.lib.integrity_backup:
                msg += f". Копия: {self.lib.integrity_backup}"
            QTimer.singleShot(0, lambda: self.notify(msg))
        self.reader = None          # последняя активная книга
        self.readers = []           # все открытые книги (многодокументный режим)
        self.flt = None
        self.scanner = None
        self.covers = None
        self.groups = {}
        self.group_colors = {}
        self.closed_tabs = []
        self._tab_history = []
        self._history_pos = 0
        self._history_lock = False
        self.setWindowTitle(f"LightRead {VER} — библиотека")
        g = self.screen().availableGeometry()
        self.resize(min(1280, int(g.width() * 0.9)), min(840, int(g.height() * 0.9)))
        self.setAcceptDrops(True)
        self._build()
        self.reload()
        if not self.lib.q("SELECT id FROM books LIMIT 1"):
            self.first_run()
        else:
            self.fetch_covers()
            if S["scan_on_start"]:
                self.scan()
        global _SESSION_RESTORED
        if not _SESSION_RESTORED:
            _SESSION_RESTORED = True
            self.restore_session()
        if S["folders"]:
            self.update_watcher()
        if S.get("update_auto") and S.get("update_url"):
            QTimer.singleShot(2000, lambda: self.check_updates(quiet=True))

    def restore_session(self):
        ids = [int(x) for x in S.get("session_tabs", []) if str(x).isdigit()]
        for bid in ids:
            if self.lib.book(bid):
                self.open_book(bid)
        self.groups = {
            g: [r for r in self.readers if r.bid in [int(x) for x in rows]]
            for g, rows in dict(S.get("session_groups", {})).items()
        }
        active = S.get("session_active")
        for r in self.readers:
            if r.bid == active:
                self.book_tabs.setCurrentWidget(r)
                break
        self._refresh_tabs()

    def _build(self):
        tb = QToolBar("Библиотека"); tb.setMovable(False); self.addToolBar(tb)

        def act(t, s, sc=None):
            a = QAction(t, self)
            if sc:
                a.setShortcut(QKeySequence(sc))
            a.triggered.connect(s); tb.addAction(a); return a

        act("Открыть файл", self.open_file, "Ctrl+O")
        act("Сканировать", self.scan, "F5")
        act("Обложки", self.fetch_covers)
        act("Папки", self.folders)
        tb.addSeparator()
        self.q = QLineEdit(); self.q.setPlaceholderText("Поиск: название, автор, серия, аннотация, заметки…")
        self.q.setAccessibleName("Поиск по библиотеке")
        self._search_timer = QTimer(self); self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.reload)
        self.q.textChanged.connect(lambda _: self._search_timer.start())
        self.q.setMaximumWidth(340); tb.addWidget(self.q)
        self.sort = QComboBox()
        for k, v in [("added_desc", "Новые"), ("title", "Название"), ("author", "Автор"),
                     ("read", "Недавно читал"), ("progress", "Прогресс"), ("series", "Серия"),
                     ("size", "Размер"), ("fmt", "Формат")]:
            self.sort.addItem(v, k)
        self.sort.setCurrentIndex(max(0, self.sort.findData(S["sort"])))
        self.sort.currentIndexChanged.connect(self.sort_changed)
        tb.addWidget(self.sort)
        act("Сетка / Список", self.toggle_view, "Ctrl+D")
        act("Настройки", self.settings, "F7")
        act("Статистика", self.stats)
        self.group_filter = QComboBox(); self.group_filter.addItem("Все вкладки")
        self.group_filter.currentTextChanged.connect(self.filter_tabs)
        tb.addWidget(self.group_filter)
        self.fav_btn = QToolButton(); self.fav_btn.setText("★ Избранное")
        self.fav_btn.setPopupMode(QToolButton.InstantPopup)
        self.fav_menu = QMenu(self.fav_btn)
        self.fav_menu.aboutToShow.connect(self.fill_fav_menu)
        self.fav_btn.setMenu(self.fav_menu)
        tb.addWidget(self.fav_btn)

        m = self.menuBar().addMenu("Файл")
        m.addAction("Открыть файл…", self.open_file)
        m.addAction("Выбрать папку библиотеки…", self.folders)
        m.addAction("Добавить папку…", self.add_folder)
        m.addAction("Сканировать", self.scan)
        m.addAction("Догрузить обложки", self.fetch_covers)
        m.addAction("Все заметки…", self.all_notes)
        m.addAction("Свойства файла…", self.file_properties, QKeySequence("Alt+Enter"))
        if S.get("show_network"):
            m.addAction("OPDS-каталоги…", self.opds)
            m.addSeparator()
            m.addAction("Синхронизация: отправить", self.sync_upload)
            m.addAction("Синхронизация: получить", self.sync_download)
            m.addSeparator()
        m.addAction("Резервная копия…", self.backup)
        m.addAction("Восстановить из копии…", self.restore)
        m.addSeparator()
        m.addAction("Выход", self.close, QKeySequence("Ctrl+Q"))
        h = self.menuBar().addMenu("Справка")
        h.addAction("Горячие клавиши", self.hotkeys)
        if S.get("show_network"):
            h.addAction("Проверить обновления…", self.check_updates)
        h.addAction("О программе", lambda: QMessageBox.about(
            self, "LightRead", f"<b>LightRead {VER}</b><br>Читалка на Qt6.<br>Данные: {DATA}"))

        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); self.tree.setMinimumWidth(170)
        self.tree.setAccessibleName("Навигация по библиотеке")
        self.tree.setItemDelegate(NavDelegate(self.tree))
        self.tree.itemClicked.connect(self.nav)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.nav_menu)
        self.model = QStandardItemModel(self)
        self.list = QListView(); self.list.setModel(self.model)
        self.list.viewport().setMouseTracking(True)
        self.list.setAccessibleName("Книги библиотеки")
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.deleg = BookDelegate(self.list)
        self.list.setItemDelegate(self.deleg)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.book_menu)
        self.list.doubleClicked.connect(self.open_from_index)
        self.list.activated.connect(self.open_from_index)
        self.set_view(S["view"])
        # пустое состояние: подсказка вместо серого поля
        self.empty = QLabel(self.list.viewport())
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setText("Пока нет книг\n\nДобавьте файл через «Файл → Открыть файл…»\nили перетащите книгу прямо в окно")
        self.empty.hide()
        self.list.viewport().installEventFilter(self)
        self.sp = QSplitter(); self.sp.addWidget(self.tree); self.sp.addWidget(self.list)
        self.sp.setStretchFactor(1, 1); self.sp.setSizes([240, 1020])
        central = QWidget(); box = QVBoxLayout(central)
        box.setContentsMargins(0, 0, 0, 0); box.setSpacing(0)
        box.addWidget(self.sp, 1)
        self.library_page = central
        self.home = HomePage(self)
        self.cont = self.home.cont
        self.cont_label = self.home.cont_label
        self.book_tabs = QTabWidget()
        self.book_tabs.setTabsClosable(True)
        self.book_tabs.tabCloseRequested.connect(self.close_tab)
        bar = self.book_tabs.tabBar()
        bar.setContextMenuPolicy(Qt.CustomContextMenu)
        bar.customContextMenuRequested.connect(self.tab_menu)
        self.book_tabs.setDocumentMode(True)
        self.book_tabs.setMovable(True)
        self.book_tabs.addTab(self.home, "Главная")
        self.book_tabs.addTab(central, "Библиотека")
        self.book_tabs.setAccessibleName("Вкладки книг")
        self.book_tabs.tabBar().setAccessibleName("Переключение вкладок")
        accent = None
        try:
            from common import ACCENT
            accent = ACCENT
        except Exception:
            accent = "#5e6ad2"
        for i, glyph in ((HOME_TAB, "⌂"), (LIB_TAB, "▤")):
            pm = QPixmap(18, 18); pm.fill(Qt.transparent)
            p = QPainter(pm); f = QFont(); f.setPointSize(12); p.setFont(f)
            p.setPen(QColor(accent)); p.drawText(pm.rect(), Qt.AlignCenter, glyph); p.end()
            self.book_tabs.setTabIcon(i, QIcon(pm))
        self.book_tabs.tabBar().setTabButton(HOME_TAB, QTabBar.RightSide, None)
        self.book_tabs.tabBar().setTabButton(LIB_TAB, QTabBar.RightSide, None)
        plus = QToolButton(); plus.setText("+"); plus.setToolTip("Новая вкладка")
        plus.setObjectName("NewTab")
        plus.clicked.connect(lambda: self.book_tabs.setCurrentIndex(HOME_TAB))
        self.book_tabs.setCornerWidget(plus, Qt.TopRightCorner)
        self.setCentralWidget(self.book_tabs)
        QShortcut(QKeySequence("Ctrl+Tab"), self, lambda: self.cycle_tab(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, lambda: self.cycle_tab(-1))
        QShortcut(QKeySequence("Ctrl+K"), self, self.command_palette)
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, self.reopen_closed_tab)
        for i in range(1, 10):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, lambda i=i: self.switch_tab_num(i))
        QShortcut(QKeySequence("Alt+Left"), self, lambda: self.tab_history(-1))
        QShortcut(QKeySequence("Alt+Right"), self, lambda: self.tab_history(1))
        find = QShortcut(QKeySequence("Ctrl+F"), self.library_page,
                         lambda: (self.book_tabs.setCurrentIndex(LIB_TAB), self.q.setFocus()))
        find.setContext(Qt.WidgetWithChildrenShortcut)
        props = QShortcut(QKeySequence("Alt+Enter"), self.library_page, self.file_properties)
        props.setContext(Qt.WidgetWithChildrenShortcut)
        self.book_tabs.currentChanged.connect(self.on_tab_changed)
        self.pb = QProgressBar(); self.pb.setMaximumWidth(220); self.pb.hide()
        self.statusBar().addPermanentWidget(self.pb)

    def update_continue(self):
        self.home.refresh()

    def continue_reading(self):
        bid = getattr(self, "_continue_id", None)
        if bid:
            self.open_book(bid)

    def build_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()

        def node(parent, text, flt, tip=None):
            it = QTreeWidgetItem(parent, [text])
            it.setData(0, Qt.UserRole, flt)
            if tip:
                it.setToolTip(0, tip)
            return it

        root = self.tree.invisibleRootItem()
        node(root, f"Все книги ({self.lib.q('SELECT COUNT(*) c FROM books')[0]['c']})", None)
        node(root, "Читаю", dict(kind="status", value="reading"))
        node(root, "Прочитано", dict(kind="status", value="read"))
        node(root, "Планирую", dict(kind="status", value="planned"))
        node(root, "Непрочитанные", dict(kind="unread"))
        node(root, "Избранное", dict(kind="fav"))
        node(root, "Недавние", dict(kind="recent"))
        n_pres = self.lib.q("SELECT COUNT(*) c FROM books WHERE fmt IN (" +
                            ",".join("?" for _ in PRESENTATION_FMTS) + ")", PRESENTATION_FMTS)[0]["c"]
        pn = node(root, f"Презентации ({n_pres})", dict(kind="presentations"))
        present = self.lib.distinct("fmt")
        for f in [f for f in present if f in PRESENTATION_FMTS]:
            node(pn, f.upper(), dict(kind="fmt", value=f))
        tn = node(root, "Метки", dict(kind="tags"))
        for t in self.lib.tags():
            node(tn, f"{t['name']} ({t['n']})", dict(kind="tag", value=t["id"]), t["name"])
        cn = node(root, "Коллекции", dict(kind="colls"))
        for c in self.lib.colls():
            node(cn, c["name"], dict(kind="coll", value=c["id"], name=c["name"]))
        mn = node(root, "Умные коллекции", dict(kind="smarts"))
        for sm in S.get("smart", []):
            node(mn, sm["name"], dict(kind="smart", value=sm["name"]))
        an = node(root, "Авторы", dict(kind="authors"))
        for a in self.lib.distinct("author"):
            node(an, a, dict(kind="author", value=a), a)
        sn = node(root, "Серии", dict(kind="series"))
        for s in self.lib.distinct("series"):
            node(sn, s, dict(kind="series", value=s), s)
        fn = node(root, "Форматы", dict(kind="fmts"))
        for f in self.lib.distinct("fmt"):
            node(fn, f.upper(), dict(kind="fmt", value=f))
        dn = node(root, "Папки", dict(kind="folders"))
        for d in self.lib.folders():
            node(dn, Path(d).name or d, dict(kind="folder", value=d), d)
        self.tree.expandToDepth(0)
        self.tree.blockSignals(False)

    def nav(self, it, _):
        f = it.data(0, Qt.UserRole)
        self.flt = f if f and f.get("kind") not in ("colls", "tags", "authors", "series", "fmts", "folders", "smarts") else None
        self.reload()

    def nav_menu(self, pos):
        it = self.tree.itemAt(pos)
        f = it.data(0, Qt.UserRole) if it else None
        m = QMenu(self)
        m.addAction("Новая коллекция…", self.new_coll)
        m.addAction("Новая метка…", self.new_tag)
        m.addAction("Новая умная коллекция…", self.new_smart)
        if f and f.get("kind") == "smart":
            m.addAction("Изменить правило…", lambda: self.edit_smart(f["value"]))
            m.addAction("Удалить правило", lambda: self.del_smart(f["value"]))
        if f and f.get("kind") == "coll":
            m.addAction("Удалить коллекцию", lambda: (self.lib.coll_drop(f["value"]), self.reload()))
        if f and f.get("kind") == "tag":
            m.addAction("Удалить метку", lambda: (self.lib.tag_drop(f["value"]), self.reload()))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def new_smart(self):
        d = SmartDialog(self.lib, parent=self)
        if d.exec():
            rule = d.values()
            if not rule["name"]:
                return
            S["smart"] = [x for x in S.get("smart", []) if x["name"] != rule["name"]]
            S["smart"].append(rule)
            S.save(); self.reload()

    def edit_smart(self, name):
        rule = next((x for x in S.get("smart", []) if x.get("name") == name), None)
        if not rule:
            return
        d = SmartDialog(self.lib, rule, self)
        if d.exec():
            new = d.values()
            S["smart"] = [new if x.get("name") == name else x for x in S.get("smart", [])]
            S.save(); self.reload()

    def del_smart(self, name):
        S["smart"] = [x for x in S.get("smart", []) if x.get("name") != name]
        self.flt = None
        S.save(); self.reload()

    def new_coll(self):
        name, ok = QInputDialog.getText(self, "Коллекция", "Название:")
        if ok and name.strip():
            self.lib.new_coll(name.strip()); self.reload()

    def new_tag(self):
        name, ok = QInputDialog.getText(self, "Метка", "Название метки:")
        if ok and name.strip():
            self.lib.new_tag(name.strip()); self.reload()

    def reload(self):
        self.build_tree()
        rows = self.lib.books(self.flt, self.q.text().strip(), self.sort.currentData())
        self.model.clear()
        for r in rows:
            it = QStandardItem(); it.setData(dict(r), ROLE); it.setEditable(False)
            self.model.appendRow(it)
        self.statusBar().showMessage(f"Книг: {len(rows)}")
        self.update_continue()
        if not rows:
            query = self.q.text().strip()
            if query:
                self.empty.setText(f"Ничего не найдено по запросу\n«{query}»\n\n"
                                   "Измените запрос или очистите поиск")
            elif self.flt and self.flt.get("kind") == "smart":
                self.empty.setText("Под это правило пока нет книг\n\n"
                                   "Измените условия умной коллекции")
            elif self.flt:
                self.empty.setText("Здесь пока нет книг\n\n"
                                   "Добавьте книги или выберите другой фильтр")
            else:
                self.empty.setText("Пока нет книг\n\n"
                                   "Добавьте файл через «Файл → Открыть файл…»\n"
                                   "или перетащите книгу прямо в окно")
        self.empty.setVisible(not rows)
        self.empty.resize(self.list.viewport().size())
        self.list.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self.width()
        tw = max(170, min(300, int(w * 0.2)))
        sizes = self.sp.sizes() if hasattr(self, "sp") else []
        if sizes and abs(sizes[0] - tw) > 60:
            self.sp.setSizes([tw, max(200, w - tw)])

    def eventFilter(self, obj, ev):
        try:
            if obj is self.list.viewport():
                if ev.type() == QEvent.Resize:
                    self.empty.resize(self.list.viewport().size())
                    self.list.scheduleDelayedItemsLayout()
                elif ev.type() == QEvent.MouseMove:
                    idx = self.list.indexAt(ev.position().toPoint())
                    data = idx.data(ROLE) if idx.isValid() else None
                    bid = data["id"] if data else None
                    if self.deleg.hover != bid:
                        self.deleg.hover = bid
                        self.list.viewport().update()
                elif ev.type() == QEvent.MouseButtonPress and self.deleg.action_rects:
                    pos = ev.position().toPoint()
                    for key, rect in self.deleg.action_rects.items():
                        if rect.contains(pos.x(), pos.y()):
                            idx = self.list.indexAt(pos)
                            data = idx.data(ROLE) if idx.isValid() else None
                            if data:
                                bid = data["id"]
                                if key == "read":
                                    self.open_book(bid)
                                elif key == "fav":
                                    self.lib.set_field(bid, favorite=0 if data["favorite"] else 1)
                                    self.reload()
                                elif key == "info":
                                    InfoDialog(self.lib, bid, self).exec()
                                    self.reload()
                            return True
                elif ev.type() == QEvent.Leave:
                    if self.deleg.hover is not None:
                        self.deleg.hover = None
                        self.list.viewport().update()
        except RuntimeError:
            return False
        return super().eventFilter(obj, ev)

    def sort_changed(self):
        S["sort"] = self.sort.currentData(); S.save(); self.reload()

    def set_view(self, mode):
        grid = mode == "grid"
        self.deleg.grid = grid
        self.deleg.bust()
        self.list.setViewMode(QListView.IconMode if grid else QListView.ListMode)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setSpacing(4)
        self.list.setUniformItemSizes(True)
        self.list.setWrapping(grid)
        S["view"] = mode; S.save()

    def toggle_view(self):
        self.set_view("list" if self.deleg.grid else "grid")

    def first_run(self):
        if QMessageBox.question(self, "Добро пожаловать",
                                "Библиотека пуста. Выбрать папку с книгами?") == QMessageBox.Yes:
            self.folders()

    def update_watcher(self):
        if not hasattr(self, "watcher"):
            self.watcher = QFileSystemWatcher(self)
            self.watcher.directoryChanged.connect(self._fs_changed)
            self.watcher.fileChanged.connect(self._fs_changed)
            self._fs_timer = QTimer(self); self._fs_timer.setSingleShot(True)
            self._fs_timer.setInterval(900); self._fs_timer.timeout.connect(self.scan)
        paths = []
        for root in S["folders"]:
            base = Path(root)
            if not base.is_dir():
                continue
            paths.append(str(base))
            paths += [str(d) for d in base.rglob("*")
                      if d.is_dir() and not d.name.startswith(".")]
        old = self.watcher.directories() + self.watcher.files()
        if old:
            self.watcher.removePaths(old)
        if paths:
            self.watcher.addPaths(paths)

    def _fs_changed(self, _path):
        self._fs_timer.start()
        self.update_watcher()

    def folders(self):
        """Выбрать корневую папку: сканируется она и все вложенные папки."""
        p = QFileDialog.getExistingDirectory(self, "Папка с книгами (сканировать со вложенными)")
        if not p:
            return
        S["folders"] = [p]
        S.save()
        self.update_watcher()
        self.statusBar().showMessage(f"Папка библиотеки: {p}", 4000)
        self.scan()

    def add_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Добавить папку с книгами")
        if not p:
            return
        if p not in S["folders"]:
            S["folders"].append(p)
            S.save()
            self.update_watcher()
            self.scan()
        else:
            self.statusBar().showMessage("Эта папка уже есть в библиотеке", 3000)

    def scan(self):
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop(); return
        if not S["folders"]:
            self.folders()
            if not S["folders"]:
                return
        self.pb.show(); self.pb.setValue(0)
        self.scanner = Scanner(S["folders"], self.lib.known(), self.lib.hashes())
        self.scanner.found.connect(self.on_found)
        self.scanner.progress.connect(lambda n, i, t: (self.pb.setMaximum(t), self.pb.setValue(i),
                                                       self.statusBar().showMessage("Скан: " + n[:70])))
        self.scanner.done.connect(self.scan_done)
        self.scanner.start()

    def on_found(self, d):
        cover = d.pop("cover", b"")
        bid = self.lib.upsert(d)
        if save_cover(bid, cover):
            self.deleg.bust(bid)

    def scan_done(self, n):
        self.pb.hide()
        self.statusBar().showMessage(f"Сканирование завершено: +{n}", 5000)
        self.notify(f"Сканирование завершено: +{n}")
        self.reload()
        self.fetch_covers()

    def fetch_covers(self):
        if self.covers and self.covers.isRunning():
            return
        jobs = [(r["id"], r["path"], r["fmt"]) for r in self.lib.q("SELECT id,path,fmt FROM books")
                if not (COVERS / f"{r['id']}.png").exists() and Path(r["path"]).is_file()]
        if not jobs:
            return
        self.statusBar().showMessage(f"Обложки: {len(jobs)}…")
        self.covers = CoverWorker(jobs)
        self.covers.got.connect(lambda bid: (self.deleg.bust(bid), self.list.viewport().update()))
        self.covers.finishedAll.connect(lambda: (
            self.statusBar().showMessage("Обложки готовы", 3000), self.notify("Обложки готовы")))
        self.covers.start()

    def open_file(self):
        extensions = " ".join(f"*{ext}" for ext in sorted(EXTS))
        ps, _ = QFileDialog.getOpenFileNames(
            self, "Открыть книги", "", f"Книги ({extensions});;Все файлы (*)")
        for p in ps:
            self.import_path(p, open_it=True)

    def import_path(self, p, open_it=False):
        try:
            with PDF_LOCK:
                m, fmt = read_meta(p)
        except FormatError as e:
            QMessageBox.warning(self, "Формат", f"{Path(p).name}\n{e}"); return None
        st = Path(p).stat()
        try:
            fhash = Scanner._fhash(p, st)
        except OSError:
            fhash = ""
        bid = self.lib.upsert(dict(path=p, fmt=fmt, title=m.title or Path(p).stem,
                                   author="; ".join(m.authors), series=m.series, seq=m.seq, lang=m.lang,
                                   annotation=m.annotation[:2000], genres="; ".join(m.genres[:8]),
                                   size=st.st_size, mtime=st.st_mtime, fhash=fhash))
        if save_cover(bid, m.cover):
            self.deleg.bust(bid)
        self.reload()
        if open_it:
            self.open_book(bid)
        else:
            self.fetch_covers()
        return bid

    def _row_data(self, idx):
        data = idx.data(ROLE) if idx is not None and idx.isValid() else None
        return data if isinstance(data, dict) else None

    def open_from_index(self, idx):
        data = self._row_data(idx)
        if data and data.get("id") is not None:
            self.open_book(data["id"])

    def open_book(self, bid):
        row = self.lib.book(bid)
        if not row:
            return
        if not Path(row["path"]).is_file():
            QMessageBox.warning(self, "Нет файла", "Файл недоступен: " + row["path"]); return
        # Если книга уже открыта — просто активируем её окно.
        for r in self.readers:
            if getattr(r, "bid", None) == bid:
                self.book_tabs.setCurrentWidget(r)
                return
        try:
            r = Reader(self.lib, row)
        except FormatError as e:
            QMessageBox.warning(self, "Не удалось открыть", str(e)); return
        except Exception as e:
            QMessageBox.critical(self, "Ошибка открытия", f"{type(e).__name__}: {e}"); return
        r.setAttribute(Qt.WA_DeleteOnClose)
        r.closed.connect(self.reader_closed)
        r.destroyed.connect(lambda _=None, rr=r: self.reader_closed(rr))
        self.readers.append(r)
        self.reader = r
        title = (row["title"] or "Без названия")[:40]
        self.book_tabs.addTab(r, title)
        idx = self.book_tabs.count() - 1
        close = QToolButton()
        close.setText("×"); close.setObjectName("TabClose")
        close.setToolTip("Закрыть вкладку"); close.setCursor(Qt.ArrowCursor)
        close.clicked.connect(lambda _=False, i=idx: self.close_tab(i))
        self.book_tabs.tabBar().setTabButton(idx, QTabBar.RightSide, close)
        self.book_tabs.setCurrentWidget(r)

    def reader_fullscreen(self, r=None):
        if getattr(self, "_reading_full", False):
            for w, vis in getattr(self, "_fs_hidden", []):
                try:
                    if vis:
                        w.show()
                except RuntimeError:
                    pass
            self._fs_hidden = []
            self._reading_full = False
            self.showNormal()
            return
        r = r or self.reader
        if r is None:
            return
        candidates = [self.menuBar(), self.statusBar(), self.book_tabs.tabBar(), self.cont]
        candidates += self.findChildren(QToolBar)
        candidates += [r.menuBar(), r.statusBar(), r.tune_host, r.dock]
        candidates += r.findChildren(QToolBar)
        hidden = [(w, w.isVisible()) for w in candidates if w is not None]
        for w, _ in hidden:
            try:
                w.hide()
            except RuntimeError:
                pass
        self._fs_hidden = hidden
        self._reading_full = True
        self.showFullScreen()

    def reopen_closed_tab(self):
        if not self.closed_tabs:
            return
        bid, group = self.closed_tabs.pop()
        if not self.lib.book(bid):
            return
        self.open_book(bid)
        if group and self.reader:
            self.assign_group(self.reader, group)

    def command_palette(self):
        d = CommandPalette(self)
        w = self
        for label, fn in (
            ("Открыть файл…", w.open_file),
            ("Выбрать папку библиотеки…", w.folders),
            ("Добавить папку…", w.add_folder),
            ("Сканировать", w.scan),
            ("Сетка / Список", w.toggle_view),
            ("Настройки", w.settings),
            ("Статистика", w.stats),
            ("Свойства файла…", w.file_properties),
            ("⌂ Главная", lambda: w.book_tabs.setCurrentIndex(HOME_TAB)),
            ("Библиотека", lambda: w.book_tabs.setCurrentIndex(LIB_TAB)),
        ):
            d.add(label, fn)
        if w.reader:
            for label, fn in (
                ("Полный экран", w.reader.fullscreen),
                ("Озвучка: вкл/выкл", w.reader.tts_toggle),
                ("Следующая страница", w.reader.view.next),
            ):
                d.add(label, fn)
        for r in w.lib.q("SELECT id,title,author FROM books ORDER BY last_read DESC LIMIT 200"):
            title = r["title"] or "Без названия"
            label = f"📖 {title}" + (f" — {r['author']}" if r["author"] else "")
            d.add(label, lambda bid=r["id"]: w.open_book(bid))
        d.fill("")
        d.exec()

    def file_properties(self, bid=None):
        if bid is None:
            idx = self.list.currentIndex()
            data = idx.data(ROLE) if idx.isValid() else None
            if not data:
                return
            bid = data["id"]
        if self.lib.book(bid):
            FilePropertiesDialog(self.lib, bid, self).exec()

    def notify(self, text):
        if not hasattr(self, "toast"):
            self.toast = Toast(self)
        self.toast.notify(text)

    def on_tab_changed(self, i):
        if self._history_lock:
            return
        if not self._tab_history or self._tab_history[self._history_pos] != i:
            self._tab_history = self._tab_history[:self._history_pos + 1] + [i]
            self._history_pos = len(self._tab_history) - 1

    def switch_tab_num(self, n):
        if n <= self.book_tabs.count():
            self.book_tabs.setCurrentIndex(n - 1)

    def tab_history(self, d):
        pos = self._history_pos + d
        if 0 <= pos < len(self._tab_history):
            self._history_pos = pos
            self._history_lock = True
            self.book_tabs.setCurrentIndex(self._tab_history[pos])
            self._history_lock = False

    def cycle_tab(self, d):
        n = self.book_tabs.count()
        if n > 1:
            self.book_tabs.setCurrentIndex((self.book_tabs.currentIndex() + d) % n)

    def fill_fav_menu(self):
        self.fav_menu.clear()
        rows = self.lib.q("SELECT id,title FROM books WHERE favorite=1 ORDER BY title LIMIT 40")
        if not rows:
            self.fav_menu.addAction("Нет избранных книг").setEnabled(False)
            return
        for r in rows:
            self.fav_menu.addAction((r["title"] or "Без названия")[:55],
                                    lambda bid=r["id"]: self.open_book(bid))

    def close_tab(self, i):
        w = self.book_tabs.widget(i)
        if isinstance(w, Reader):
            w.close()
        elif i > LIB_TAB:
            self.book_tabs.removeTab(i)

    def tab_menu(self, pos):
        bar = self.book_tabs.tabBar()
        i = bar.tabAt(pos)
        if i <= LIB_TAB:
            return
        w = self.book_tabs.widget(i)
        if not isinstance(w, Reader):
            return
        m = QMenu(self)
        m.addAction("Закрыть вкладку", lambda: self.close_tab(i))
        m.addSeparator()
        m.addAction("Новая группа…", lambda: self.assign_group(w))
        for g in self.groups:
            m.addAction(f"В группу: {g}", lambda g=g, w=w: self.assign_group(w, g))
        current_group = next((g for g, rows in self.groups.items() if w in rows), "")
        if current_group:
            m.addAction("Свернуть/развернуть группу",
                        lambda g=current_group: self.group_filter.setCurrentText(
                            "Все вкладки" if self.group_filter.currentText() == g else g))
            m.addAction("Без группы", lambda: self.assign_group(w, ""))
        m.exec(bar.mapToGlobal(pos))

    def assign_group(self, r, name=None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Группа вкладок", "Название группы:")
            if not ok or not name.strip():
                return
            name = name.strip()
        for other in list(self.groups):
            rows = self.groups[other]
            if r in rows:
                rows.remove(r)
            if not rows:
                del self.groups[other]
        if name:
            self.groups.setdefault(name, [])
            if name not in self.group_colors:
                self.group_colors[name] = GROUP_COLORS[len(self.group_colors) % len(GROUP_COLORS)]
            self.groups[name].append(r)
        self._refresh_tabs()

    def _refresh_tabs(self):
        current = self.group_filter.currentText()
        self.group_filter.blockSignals(True)
        self.group_filter.clear(); self.group_filter.addItem("Все вкладки")
        self.group_filter.addItems(list(self.groups))
        self.group_filter.setCurrentText(current if current in ("Все вкладки", *self.groups) else "Все вкладки")
        self.group_filter.blockSignals(False)
        for i in range(LIB_TAB + 1, self.book_tabs.count()):
            w = self.book_tabs.widget(i)
            if not isinstance(w, Reader):
                continue
            group = next((g for g, rows in self.groups.items() if w in rows), "")
            title = (w.row["title"] or "Без названия")[:34]
            self.book_tabs.setTabText(i, f"{group}: {title}" if group else title)
            if group:
                color = QColor(self.group_colors.get(group, GROUP_COLORS[0]))
                pm = QPixmap(10, 10); pm.fill(Qt.transparent)
                q = QPainter(pm); q.setRenderHint(QPainter.Antialiasing, True)
                q.setPen(Qt.NoPen); q.setBrush(color); q.drawEllipse(1, 1, 8, 8); q.end()
                self.book_tabs.setTabIcon(i, QIcon(pm))
            else:
                self.book_tabs.setTabIcon(i, QIcon())
        self.filter_tabs(self.group_filter.currentText())

    def filter_tabs(self, name):
        for i in range(self.book_tabs.count()):
            w = self.book_tabs.widget(i)
            show = True
            if i > LIB_TAB and isinstance(w, Reader) and name != "Все вкладки":
                show = w in self.groups.get(name, [])
            self.book_tabs.tabBar().setTabVisible(i, show)

    def reader_closed(self, r):
        try:
            if r not in self.readers and all(self.book_tabs.widget(i) is not r
                                             for i in range(self.book_tabs.count())):
                return
            group = next((g for g, rows in self.groups.items() if r in rows), "")
            self.closed_tabs.append((r.bid, group))
            if len(self.closed_tabs) > 20:
                self.closed_tabs.pop(0)
            for g in list(self.groups):
                if r in self.groups[g]:
                    self.groups[g].remove(r)
                if not self.groups[g]:
                    del self.groups[g]
            for i in range(self.book_tabs.count()):
                if self.book_tabs.widget(i) is r:
                    self.book_tabs.removeTab(i)
                    break
            if r in self.readers:
                self.readers.remove(r)
            if self.reader is r:
                self.reader = self.readers[-1] if self.readers else None
            self._refresh_tabs()
            self.reload()
        except RuntimeError:
            # Окно уже Destroyed во время выхода приложения.
            pass

    def book_menu(self, pos):
        idx = self.list.indexAt(pos)
        b = self._row_data(idx)
        if b is None or b.get("id") is None:
            return
        if idx not in self.list.selectedIndexes():
            self.list.setCurrentIndex(idx)
        ids = []
        for i in self.list.selectedIndexes():
            data = self._row_data(i)
            if data and data.get("id") is not None:
                ids.append(data["id"])
        if not ids:
            ids = [b["id"]]
        many = len(ids) > 1
        bid = b["id"]
        m = QMenu(self)
        if many:
            m.addAction(f"Выбрано книг: {len(ids)}").setEnabled(False)
        else:
            m.addAction("Читать", lambda: self.open_book(bid))
            m.addAction("Информация…", lambda: (InfoDialog(self.lib, bid, self).exec(), self.reload()))
            m.addAction("Свойства файла…", lambda: self.file_properties(bid))
        m.addSeparator()
        st = m.addMenu("Статус")
        for s, t in [("new", "Не начата"), ("reading", "Читаю"), ("read", "Прочитано"), ("planned", "Планирую")]:
            st.addAction(t, lambda ss=s: ([self.lib.set_field(i, status=ss) for i in ids], self.reload()))
        if many:
            m.addAction("В избранное", lambda: ([self.lib.set_field(i, favorite=1) for i in ids], self.reload()))
        else:
            m.addAction("Избранное", lambda: (self.lib.set_field(bid, favorite=0 if b.get("favorite") else 1), self.reload()))
        cm = m.addMenu("В коллекцию")
        for c in self.lib.colls():
            cm.addAction(c["name"], lambda cc=c: ([self.lib.coll_add(cc["id"], i) for i in ids], self.reload()))
        cm.addAction("Новая…", lambda: (self.new_coll(), self.reload()))
        m.addSeparator()
        if not many:
            m.addAction("Обновить обложку", lambda: self.refresh_cover(bid))
            m.addAction("Показать в папке", lambda: self.reveal(b.get("path", "")))
        m.addAction("Сбросить прогресс", lambda: ([self.lib.set_progress(i, 0, 0, 0.0) for i in ids], self.reload()))
        m.addAction("Убрать из библиотеки", lambda: ([self.lib.remove(i) for i in ids], self.reload()))
        m.addAction("Удалить файлы…", lambda: self.delete_many(ids) if many else self.delete_file(bid))
        m.exec(self.list.viewport().mapToGlobal(pos))

    def delete_many(self, ids):
        if QMessageBox.question(self, "Удалить", f"Удалить {len(ids)} файлов с диска?") != QMessageBox.Yes:
            return
        for bid in ids:
            self.lib.remove(bid, delete_file=True)
        self.reload()

    def refresh_cover(self, bid):
        f = COVERS / f"{bid}.png"
        try:
            f.unlink()
        except OSError:
            pass
        self.deleg.bust(bid)
        self.fetch_covers()

    def delete_file(self, bid):
        if QMessageBox.question(self, "Удалить", "Удалить файл с диска?") == QMessageBox.Yes:
            self.lib.remove(bid, delete_file=True); self.reload()

    def reveal(self, path):
        p = Path(path)
        if sys.platform.startswith("win"):
            # explorer ожидает один аргумент /select,",путь" — иначе открывает
            # родительскую папку без выделения файла.
            subprocess.Popen(["explorer", f'/select,"{p}"'])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))

    def settings(self):
        d = SettingsDialog(dict(S), self)
        if d.exec():
            S.update(d.s); S.save()
            apply_theme(S["theme"], force=True)
            self.set_view(S["view"]); self.reload()

    def stats(self):
        StatsDialog(self.lib, self).exec()

    def all_notes(self):
        AllNotesDialog(self.lib, self).exec()

    def opds(self):
        OpdsDialog(self).exec()

    def check_updates(self, quiet=False):
        from services import Update
        if not S.get("update_url"):
            if not quiet:
                self.statusBar().showMessage("Укажи URL релизов в настройках", 4000)
            return
        try:
            info = Update(S["update_url"]).check()
            ver = info.get("version", "")
            if quiet:
                if ver:
                    self.statusBar().showMessage(f"Доступна версия {ver}", 5000)
            else:
                text = f"Доступна версия: {ver}"
                if info.get("url"):
                    text += f"\n\n{info['url']}"
                if info.get("notes"):
                    text += f"\n\n{info['notes']}"
                QMessageBox.information(self, "Обновления", text)
        except Exception as e:
            if not quiet:
                QMessageBox.information(self, "Обновления",
                                        f"Не удалось проверить: {type(e).__name__}: {e}")

    def _sync_client(self):
        from services import WebDav
        if not S.get("webdav_url"):
            return None
        return WebDav(S["webdav_url"], S.get("webdav_user", ""), S.get("webdav_password", ""))

    def sync_upload(self, quiet=False):
        from services import Sync
        client = self._sync_client()
        if not client:
            if not quiet:
                self.statusBar().showMessage("Укажи WebDAV URL в настройках", 4000)
            return
        try:
            client.ensure()
            client.put(Sync.NAME, json.dumps(Sync.export(self.lib), ensure_ascii=False).encode("utf-8"))
            if not quiet:
                self.statusBar().showMessage("Синхронизация: данные отправлены", 4000)
                self.notify("Синхронизация: данные отправлены")
        except Exception as e:
            self.statusBar().showMessage(f"Ошибка синхронизации: {type(e).__name__}", 5000)

    def sync_download(self):
        from services import Sync
        client = self._sync_client()
        if not client:
            self.statusBar().showMessage("Укажи WebDAV URL в настройках", 4000)
            return
        try:
            data = json.loads(client.get(Sync.NAME).decode("utf-8"))
            Sync.apply(self.lib, data)
            self.reload()
            self.statusBar().showMessage("Синхронизация: данные получены", 4000)
            self.notify("Синхронизация: данные получены")
        except Exception as e:
            self.statusBar().showMessage(f"Ошибка синхронизации: {type(e).__name__}", 5000)

    def backup(self):
        p, _ = QFileDialog.getSaveFileName(self, "Резервная копия", "lightread-backup.zip", "ZIP (*.zip)")
        if not p:
            return
        self.lib.c.commit()
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(DB, "library.db")
            if (DATA / "settings.json").exists():
                z.write(DATA / "settings.json", "settings.json")
            for f in COVERS.glob("*.png"):
                z.write(f, "covers/" + f.name)
        QMessageBox.information(self, "Готово", "Копия сохранена.")

    def restore(self):
        p, _ = QFileDialog.getOpenFileName(self, "Восстановить", "", "ZIP (*.zip)")
        if not p:
            return
        with zipfile.ZipFile(p) as z:
            z.extractall(DATA)
        QMessageBox.information(self, "Готово", "Восстановлено. Перезапустите LightRead.")

    def hotkeys(self):
        QMessageBox.information(self, "Горячие клавиши", """
<b>Главная</b>: Ctrl+1 главная · Ctrl+2 библиотека · Ctrl+K команды · Ctrl+Shift+T вернуть вкладку
<b>Библиотека</b>: Ctrl+O открыть · F5 скан · Ctrl+D вид · F7 настройки · Ctrl+F поиск · Alt+Enter свойства файла
<b>Чтение</b>: Space/PgDn вперёд · PgUp назад · Home/End начало/конец · Ctrl+←/→ глава
F4 навигация · Ctrl+F поиск · Ctrl+B закладка · Ctrl+N заметки · Ctrl+T озвучка
Ctrl+R автопрокрутка · F5 тема · F6 панель настройки · F11 полный экран · Ctrl+W закрыть
<b>PDF</b>: колесо — прокрутка, Ctrl+колесо — зум под курсором, перетаскивание — панорама,
0 — по ширине, 9 — по странице, +/− — масштаб.
""")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).is_dir():
                if p not in S["folders"]:
                    S["folders"].append(p); S.save()
                    self.update_watcher()
                self.scan()
            elif Path(p).suffix.lower() in EXTS:
                self.import_path(p)

    def closeEvent(self, e):
        for w in (self.scanner, self.covers):
            if w and w.isRunning():
                w.stop(); w.wait(2000)
        S["session_tabs"] = [r.bid for r in self.readers]
        S["session_active"] = self.reader.bid if self.reader else None
        S["session_groups"] = {g: [r.bid for r in rows] for g, rows in self.groups.items()}
        if S.get("webdav_auto"):
            self.sync_upload(quiet=True)
        # Закрываем все окна чтения, чтобы сохранить позиции и статистику.
        for r in list(self.readers):
            try:
                r.close()
            except Exception:
                pass
        S.save()
        e.accept()