"""Библиотека: обложки, аккуратные карточки, сканер, диалоги."""
import os, subprocess, sys, time, zipfile
from collections import OrderedDict
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QSize, QRect, QRectF, QUrl, QEvent, QTimer
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QImage, QPainter, QPixmap,
                           QKeySequence, QStandardItem, QStandardItemModel, QPalette,
                           QLinearGradient, QPen, QPainterPath)
from PySide6.QtWidgets import (QMainWindow, QListView, QStyledItemDelegate, QStyle, QTreeWidget,
                               QTreeWidgetItem, QSplitter, QToolBar, QLineEdit, QComboBox, QWidget,
                               QVBoxLayout, QHBoxLayout, QFormLayout, QDialog, QDialogButtonBox,
                               QTabWidget, QSpinBox, QDoubleSpinBox, QCheckBox, QFontComboBox,
                               QLabel, QFileDialog, QMessageBox, QMenu, QInputDialog, QProgressBar,
                               QListWidget, QListWidgetItem, QPushButton, QApplication, QSlider)

from common import (S, DATA, DB, COVERS, THEMES, VER, ACCENT, ACCENT2, OK, WARN, BAD,
                    human, hms, norm, theme)
from formats import ALL_EXTS, open_source, read_meta, FormatError
from library import Library
from reader import Reader
from views import PDF_LOCK
from theming import apply_theme, chrome

EXTS = ALL_EXTS
ROLE = Qt.UserRole + 1
FMT_COLOR = {"pdf": "#ff5470", "epub": "#3ecf8e", "fb2": "#4c8dff", "djvu": "#c39bff",
             "docx": "#5cc8ff", "mobi": "#ffc94a", "azw3": "#ffc94a", "txt": "#97a1b0"}


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

    def __init__(self, folders, known):
        super().__init__()
        self.folders, self.known, self._stop = folders, known, False

    def stop(self): self._stop = True

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
        for i, (p, st) in enumerate(files):
            if self._stop:
                break
            self.progress.emit(p.name, i + 1, len(files))
            try:
                with PDF_LOCK:
                    m, fmt = read_meta(str(p))
            except Exception:
                continue
            self.found.emit(dict(path=str(p), fmt=fmt, title=m.title or p.stem,
                                 author="; ".join(a for a in m.authors if a), series=m.series, seq=m.seq,
                                 lang=m.lang, annotation=m.annotation[:2000], genres="; ".join(m.genres[:8]),
                                 size=st.st_size, mtime=st.st_mtime, cover=m.cover))
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
        self._pix = OrderedDict()
        self._scaled = OrderedDict()
        self._miss = set()
        self._c = chrome(theme(S["theme"]))
        self._dark = theme(S["theme"])["dark"]

    def bust(self, bid=None):
        self._c = chrome(theme(S["theme"]))
        self._dark = theme(S["theme"])["dark"]
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

    def sizeHint(self, opt, idx):
        return QSize(192, 306) if self.grid else QSize(520, 86)

    @staticmethod
    def _scolor(b):
        return {"read": OK, "reading": ACCENT2, "planned": "#8b95a4"}.get(b["status"], ACCENT)

    def _round(self, box, r=13):
        path = QPainterPath()
        path.addRoundedRect(box, r, r)
        return path

    def _pill(self, p, rect, text, color, size=8):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._c["chip"]))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setPen(QColor(color))
        f = p.font(); f.setPointSize(size); f.setBold(True); p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, text)

    def _placeholder(self, p, box, b):
        col = QColor(FMT_COLOR.get(b["fmt"], "#6b7686"))
        g = QLinearGradient(box.topLeft(), box.bottomRight())
        if self._dark:
            g.setColorAt(0.0, QColor("#252d3a")); g.setColorAt(1.0, QColor("#141920"))
            tint_alpha, title_col = 62, QColor(255, 255, 255, 225)
            label_col = col.lighter(165)
        else:
            g.setColorAt(0.0, QColor("#dbd4c7")); g.setColorAt(1.0, QColor("#c3baab"))
            tint_alpha, title_col = 42, QColor("#33302a")
            label_col = col.darker(150)
        p.setPen(Qt.NoPen)
        p.fillPath(self._round(box), g)
        tint = QColor(col); tint.setAlpha(tint_alpha)
        p.setBrush(tint)
        p.drawRoundedRect(box, 10, 10)
        # «корешок» и тонкая линия — заглушка похожа на обложку
        spine = QColor(col); spine.setAlpha(150)
        p.setBrush(spine)
        p.drawRoundedRect(QRectF(box.x(), box.y(), 8, box.height()), 4, 4)
        p.setBrush(Qt.NoBrush)  # иначе контур закрасит обложку ещё раз
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(box.x() + 18, box.y() + 58, box.right() - 18, box.y() + 58)
        p.drawPath(self._round(box))
        p.setPen(title_col)
        f = p.font(); f.setPointSize(10); f.setBold(True); p.setFont(f)
        p.drawText(box.adjusted(14, 14, -12, -40), Qt.AlignTop | Qt.TextWordWrap, b["title"][:70])
        p.setPen(label_col)
        f.setPointSize(8); f.setBold(True); p.setFont(f)
        p.drawText(box.adjusted(14, 0, -12, -12), Qt.AlignBottom | Qt.AlignLeft, b["fmt"].upper())

    def _cover(self, p, box, b, pm):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._c["shadow"]))
        p.drawRoundedRect(box.adjusted(2, 5, 2, -3), 10, 10)
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
        p.setPen(QPen(QColor(255, 255, 255, 34), 1))
        p.drawRoundedRect(box, 11, 11)

    def paint(self, p, opt, idx):
        b = idx.data(ROLE)
        if not b:
            return
        c = self._c
        fg = QColor(c["text"]); dim = QColor(c["dim"])
        accent = QColor(c["accent"]); sel = QColor(c["sel"])
        status = self._scolor(b)
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(opt.rect).adjusted(9, 9, -9, -9)
        if opt.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen); p.setBrush(sel)
            p.drawRoundedRect(QRectF(opt.rect).adjusted(3, 3, -3, -3), 16, 16)
        pm = self.pix(b["id"])

        if self.grid:
            cover = QRectF(r.x(), r.y(), r.width(), r.height() * 0.655)
            self._cover(p, cover, b, pm)
            # статусный бейдж поверх обложки
            labels = {"reading": "ЧИТАЮ", "read": "ПРОЧИТАНО", "planned": "ПЛАН"}
            if b["status"] in labels:
                bw = 68 if b["status"] == "read" else 54
                self._pill(p, QRectF(cover.x() + 9, cover.y() + 9, bw, 19),
                           labels[b["status"]], status, 7)
            if b["favorite"]:
                star = QRectF(cover.right() - 32, cover.y() + 7, 25, 25)
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 110))
                p.drawEllipse(star)
                p.setPen(QColor(WARN))
                f = p.font(); f.setPointSize(12); f.setBold(True); p.setFont(f)
                p.drawText(star, Qt.AlignCenter, "★")

            ty = cover.bottom() + 11
            f = p.font(); f.setPointSize(10); f.setBold(True); p.setFont(f); p.setPen(fg)
            fm = p.fontMetrics()
            line1 = fm.elidedText(b["title"], Qt.ElideRight, int(r.width()))
            p.drawText(QRectF(r.x(), ty, r.width(), 17), Qt.AlignLeft | Qt.AlignVCenter, line1)
            rest = b["title"][max(0, len(line1) - 1):] if line1.endswith("…") else ""
            if rest:
                line2 = fm.elidedText(rest, Qt.ElideRight, int(r.width()))
                p.drawText(QRectF(r.x(), ty + 16, r.width(), 17), Qt.AlignLeft | Qt.AlignVCenter, line2)
                ty += 16
            f.setPointSize(9); f.setBold(False); p.setFont(f); p.setPen(dim)
            p.drawText(QRectF(r.x(), ty + 18, r.width(), 15), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(b["author"] or "Автор не указан", Qt.ElideRight, int(r.width())))
            # строка метаданных: формат + прогресс
            my = cover.bottom() + 68
            fmt_col = QColor(FMT_COLOR.get(b["fmt"], "#97a1b0"))
            p.setBrush(Qt.NoBrush); p.setPen(Qt.NoPen)
            p.setBrush(fmt_col)
            p.drawRoundedRect(QRectF(r.x() + 1, my + 5, 6, 6), 3, 3)
            p.setPen(dim); f.setPointSize(8); p.setFont(f)
            p.drawText(QRectF(r.x() + 12, my, r.width() - 46, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{b['fmt'].upper()} · {human(b['size'])}")
            p.setPen(status); f.setBold(True); p.setFont(f)
            p.drawText(QRectF(r.right() - 44, my, 44, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{b['progress'] * 100:.0f}%")
            bar = QRectF(r.x(), r.bottom() - 9, r.width(), 6)
        else:
            cw, chh = 50.0, r.height()
            box = QRectF(r.x(), r.y(), cw, chh)
            self._cover(p, box, b, pm)
            tx = r.x() + cw + 14
            # цветная точка статуса и звёздочка избранного перед названием
            p.setPen(Qt.NoPen); p.setBrush(status)
            p.drawRoundedRect(QRectF(tx, r.y() + 10, 6, 6), 3, 3)
            title_x = tx + 13
            if b["favorite"]:
                p.setPen(QColor(WARN))
                f = p.font(); f.setPointSize(11); f.setBold(True); p.setFont(f)
                p.drawText(QRectF(tx + 10, r.y() + 1, 16, 18), Qt.AlignLeft | Qt.AlignVCenter, "★")
                title_x += 20
            tw = r.right() - 126 - title_x
            f = p.font(); f.setPointSize(11.5); f.setBold(True); p.setFont(f); p.setPen(fg)
            p.drawText(QRectF(title_x, r.y() + 2, tw, 21), Qt.AlignVCenter,
                       p.fontMetrics().elidedText(b["title"], Qt.ElideRight, int(tw)))
            f.setPointSize(9); f.setBold(False); p.setFont(f); p.setPen(dim)
            sub = (b["author"] or "Автор не указан") + (" · " + b["series"] if b["series"] else "")
            p.drawText(QRectF(title_x, r.y() + 24, tw, 16), Qt.AlignVCenter,
                       p.fontMetrics().elidedText(sub, Qt.ElideRight, int(tw)))
            # правый блок: формат, размер, процент
            rx = r.right() - 118
            f.setPointSize(8); f.setBold(True); p.setFont(f)
            fmt_col = QColor(FMT_COLOR.get(b["fmt"], "#97a1b0"))
            self._pill(p, QRectF(rx, r.y() + 6, 60, 20), b["fmt"].upper(), fmt_col, 8)
            p.setPen(dim); f.setBold(False); p.setFont(f)
            p.drawText(QRectF(rx + 66, r.y() + 6, 52, 20), Qt.AlignRight | Qt.AlignVCenter,
                       human(b["size"]))
            p.setPen(status); f.setBold(True); p.setFont(f)
            p.drawText(QRectF(rx, r.y() + 28, 118, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{b['progress'] * 100:.0f}%")
            bar = QRectF(tx, r.bottom() - 9, r.width() - (tx - r.x()), 6)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["track"]))
        p.drawRoundedRect(bar, bar.height() / 2, bar.height() / 2)
        p.setBrush(status)
        p.drawRoundedRect(QRectF(bar.x(), bar.y(),
                                 max(bar.height(), bar.width() * min(1.0, b["progress"])),
                                 bar.height()), bar.height() / 2, bar.height() / 2)
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
    ("Тема", [("theme", "Тема чтения", "choice", list(THEMES))]),
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
    ]),
    ("Библиотека", [
        ("folders", "Папки сканирования", "paths"), ("scan_on_start", "Сканировать при запуске", "bool"),
        ("save_per_book", "Запоминать настройки для каждой книги", "bool"),
    ]),
]


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None, live=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки"); self.resize(600, 660)
        self.s, self.live = settings, live
        lay = QVBoxLayout(self)
        tabs = QTabWidget(); lay.addWidget(tabs)
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
        lay.addWidget(bb)

    def set(self, k, v):
        self.s[k] = v
        if self.live:
            self.live({k: v})


class InfoDialog(QDialog):
    def __init__(self, lib, bid, parent=None):
        super().__init__(parent)
        self.lib, self.bid = lib, bid
        b = lib.book(bid)
        self.setWindowTitle("О книге"); self.resize(600, 520)
        lay = QVBoxLayout(self)
        top = QHBoxLayout(); lay.addLayout(top)
        cov = QLabel(); pm = QPixmap(str(COVERS / f"{bid}.png"))
        if not pm.isNull():
            cov.setPixmap(pm.scaled(160, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(cov)
        txt = QLabel(f"<h3>{b['title']}</h3><b>Автор:</b> {b['author'] or '—'}<br>"
                     f"<b>Серия:</b> {b['series'] or '—'}<br>"
                     f"<b>Формат:</b> {b['fmt'].upper()} · {human(b['size'])}<br>"
                     f"<b>Язык:</b> {b['lang'] or '—'}<br><b>Прогресс:</b> {b['progress'] * 100:.1f}%<br>"
                     f"<b>Чтение:</b> {hms(b['seconds'])}")
        txt.setWordWrap(True); top.addWidget(txt, 1)
        ann = QLabel(b["annotation"] or ""); ann.setWordWrap(True)
        lay.addWidget(ann)
        row = QHBoxLayout()
        self.status = QComboBox(); self.status.addItems(["new", "reading", "read", "planned"])
        self.status.setCurrentText(b["status"])
        self.status.currentTextChanged.connect(lambda v: lib.set_field(bid, status=v))
        self.fav = QCheckBox("Избранное"); self.fav.setChecked(bool(b["favorite"]))
        self.fav.toggled.connect(lambda v: lib.set_field(bid, favorite=int(v)))
        row.addWidget(QLabel("Статус:")); row.addWidget(self.status); row.addWidget(self.fav); row.addStretch()
        lay.addLayout(row)
        self.colls = QListWidget(); self.colls.setMaximumHeight(130)
        have = lib.book_colls(bid)
        for c in lib.colls():
            it = QListWidgetItem(c["name"]); it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if c["id"] in have else Qt.Unchecked)
            it.setData(Qt.UserRole, c["id"]); self.colls.addItem(it)
        self.colls.itemChanged.connect(self.coll_changed)
        lay.addWidget(QLabel("Коллекции:")); lay.addWidget(self.colls)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject); bb.accepted.connect(self.accept)
        lay.addWidget(bb)

    def coll_changed(self, it):
        cid = it.data(Qt.UserRole)
        if it.checkState() == Qt.Checked:
            self.lib.coll_add(cid, self.bid)
        else:
            self.lib.coll_del(cid, self.bid)


class Win(QMainWindow):
    def __init__(self):
        super().__init__()
        apply_theme(S["theme"], force=True)
        self.lib = Library()
        self.reader = None          # последняя активная книга
        self.readers = []           # все открытые книги (многодокументный режим)
        self.flt = None
        self.scanner = None
        self.covers = None
        self.setWindowTitle(f"LightRead {VER} — библиотека")
        self.resize(1280, 840)
        self.setAcceptDrops(True)
        self._build()
        self.reload()
        if not self.lib.q("SELECT id FROM books LIMIT 1"):
            self.first_run()
        else:
            self.fetch_covers()
            if S["scan_on_start"]:
                self.scan()

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
        self.q = QLineEdit(); self.q.setPlaceholderText("Поиск: название, автор, серия…")
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

        m = self.menuBar().addMenu("Файл")
        m.addAction("Открыть файл…", self.open_file)
        m.addAction("Добавить папку…", self.folders)
        m.addAction("Сканировать", self.scan)
        m.addAction("Догрузить обложки", self.fetch_covers)
        m.addSeparator()
        m.addAction("Резервная копия…", self.backup)
        m.addAction("Восстановить из копии…", self.restore)
        m.addSeparator()
        m.addAction("Выход", self.close, QKeySequence("Ctrl+Q"))
        h = self.menuBar().addMenu("Справка")
        h.addAction("Горячие клавиши", self.hotkeys)
        h.addAction("О программе", lambda: QMessageBox.about(
            self, "LightRead", f"<b>LightRead {VER}</b><br>Читалка на Qt6.<br>Данные: {DATA}"))

        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); self.tree.setMinimumWidth(230)
        self.tree.itemClicked.connect(self.nav)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.nav_menu)
        self.model = QStandardItemModel(self)
        self.list = QListView(); self.list.setModel(self.model)
        self.deleg = BookDelegate(self)
        self.list.setItemDelegate(self.deleg)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.book_menu)
        self.list.doubleClicked.connect(lambda i: self.open_book(i.data(ROLE)["id"]))
        self.set_view(S["view"])
        # пустое состояние: подсказка вместо серого поля
        self.empty = QLabel(self.list.viewport())
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setText("Пока нет книг\n\nДобавьте файл через «Файл → Открыть файл…»\nили перетащите книгу прямо в окно")
        self.empty.hide()
        self.list.viewport().installEventFilter(self)
        sp = QSplitter(); sp.addWidget(self.tree); sp.addWidget(self.list)
        sp.setStretchFactor(1, 1); sp.setSizes([240, 1020])
        self.setCentralWidget(sp)
        self.pb = QProgressBar(); self.pb.setMaximumWidth(220); self.pb.hide()
        self.statusBar().addPermanentWidget(self.pb)

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
        cn = node(root, "Коллекции", dict(kind="colls"))
        for c in self.lib.colls():
            node(cn, c["name"], dict(kind="coll", value=c["id"], name=c["name"]))
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
        self.flt = f if f and f.get("kind") not in ("colls", "authors", "series", "fmts", "folders") else None
        self.reload()

    def nav_menu(self, pos):
        it = self.tree.itemAt(pos)
        f = it.data(0, Qt.UserRole) if it else None
        m = QMenu(self)
        m.addAction("Новая коллекция…", self.new_coll)
        if f and f.get("kind") == "coll":
            m.addAction("Удалить коллекцию", lambda: (self.lib.coll_drop(f["value"]), self.reload()))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def new_coll(self):
        name, ok = QInputDialog.getText(self, "Коллекция", "Название:")
        if ok and name.strip():
            self.lib.new_coll(name.strip()); self.reload()

    def reload(self):
        self.build_tree()
        rows = self.lib.books(self.flt, self.q.text().strip(), self.sort.currentData())
        self.model.clear()
        for r in rows:
            it = QStandardItem(); it.setData(dict(r), ROLE); it.setEditable(False)
            self.model.appendRow(it)
        self.statusBar().showMessage(f"Книг: {len(rows)}")
        self.empty.setVisible(not rows)
        self.empty.resize(self.list.viewport().size())
        self.list.viewport().update()

    def eventFilter(self, obj, ev):
        if obj is self.list.viewport() and ev.type() == QEvent.Resize:
            self.empty.resize(self.list.viewport().size())
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
                                "Библиотека пуста. Добавить стандартные папки и сканировать?") == QMessageBox.Yes:
            home = Path.home()
            S["folders"] = [str(p) for p in (home / "Documents", home / "Downloads", home / "Books",
                                             home / "Документы", home / "Загрузки") if p.is_dir()]
            S.save(); self.scan()

    def folders(self):
        dlg = SettingsDialog(dict(S), self)
        dlg.exec()
        S.update(dlg.s); S.save()

    def scan(self):
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop(); return
        if not S["folders"]:
            self.folders()
            if not S["folders"]:
                return
        self.pb.show(); self.pb.setValue(0)
        self.scanner = Scanner(S["folders"], self.lib.known())
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
        self.covers.finishedAll.connect(lambda: self.statusBar().showMessage("Обложки готовы", 3000))
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
        bid = self.lib.upsert(dict(path=p, fmt=fmt, title=m.title or Path(p).stem,
                                   author="; ".join(m.authors), series=m.series, seq=m.seq, lang=m.lang,
                                   annotation=m.annotation[:2000], genres="; ".join(m.genres[:8]),
                                   size=st.st_size, mtime=st.st_mtime))
        if save_cover(bid, m.cover):
            self.deleg.bust(bid)
        self.reload()
        if open_it:
            self.open_book(bid)
        else:
            self.fetch_covers()
        return bid

    def open_book(self, bid):
        row = self.lib.book(bid)
        if not row:
            return
        if not Path(row["path"]).is_file():
            QMessageBox.warning(self, "Нет файла", "Файл недоступен: " + row["path"]); return
        # Если книга уже открыта — просто активируем её окно.
        for r in self.readers:
            if getattr(r, "bid", None) == bid:
                r.raise_(); r.activateWindow(); return
        try:
            r = Reader(self.lib, row)
        except FormatError as e:
            QMessageBox.warning(self, "Не удалось открыть", str(e)); return
        except Exception as e:
            QMessageBox.critical(self, "Ошибка открытия", f"{type(e).__name__}: {e}"); return
        r.setAttribute(Qt.WA_DeleteOnClose)
        r.destroyed.connect(lambda _=None, rr=r: self.reader_closed(rr))
        self.readers.append(r)
        self.reader = r
        r.show(); r.raise_(); r.activateWindow()

    def reader_closed(self, r):
        if r in self.readers:
            self.readers.remove(r)
        if self.reader is r:
            self.reader = self.readers[-1] if self.readers else None
        try:
            self.reload()
        except RuntimeError:
            # Библиотека уже Destroyed во время выхода приложения.
            pass

    def book_menu(self, pos):
        idx = self.list.indexAt(pos)
        if not idx.isValid():
            return
        b = idx.data(ROLE); bid = b["id"]
        m = QMenu(self)
        m.addAction("Читать", lambda: self.open_book(bid))
        m.addAction("Информация…", lambda: (InfoDialog(self.lib, bid, self).exec(), self.reload()))
        m.addSeparator()
        st = m.addMenu("Статус")
        for s, t in [("new", "Не начата"), ("reading", "Читаю"), ("read", "Прочитано"), ("planned", "Планирую")]:
            st.addAction(t, lambda ss=s: (self.lib.set_field(bid, status=ss), self.reload()))
        m.addAction("Избранное", lambda: (self.lib.set_field(bid, favorite=0 if b["favorite"] else 1), self.reload()))
        cm = m.addMenu("В коллекцию")
        for c in self.lib.colls():
            cm.addAction(c["name"], lambda cc=c: (self.lib.coll_add(cc["id"], bid), self.reload()))
        cm.addAction("Новая…", lambda: (self.new_coll(), self.reload()))
        m.addSeparator()
        m.addAction("Обновить обложку", lambda: self.refresh_cover(bid))
        m.addAction("Сбросить прогресс", lambda: (self.lib.set_progress(bid, 0, 0, 0.0), self.reload()))
        m.addAction("Показать в папке", lambda: self.reveal(b["path"]))
        m.addAction("Убрать из библиотеки", lambda: (self.lib.remove(bid), self.reload()))
        m.addAction("Удалить файл…", lambda: self.delete_file(bid))
        m.exec(self.list.viewport().mapToGlobal(pos))

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
        rows = self.lib.stats()
        total = self.lib.q("SELECT SUM(seconds) s FROM books")[0]["s"] or 0
        txt = f"<h3>Статистика чтения</h3><p>Всего: <b>{hms(total)}</b></p><table cellpadding=4>"
        txt += "<tr><th>Дата</th><th>Время</th><th>Страниц</th></tr>"
        for r in rows:
            txt += f"<tr><td>{r['day']}</td><td>{hms(r['s'])}</td><td>{int(r['p'] or 0)}</td></tr>"
        QMessageBox.information(self, "Статистика", txt + "</table>")

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
<b>Библиотека</b>: Ctrl+O открыть · F5 скан · Ctrl+D вид · F7 настройки
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
                self.scan()
            elif Path(p).suffix.lower() in EXTS:
                self.import_path(p)

    def closeEvent(self, e):
        for w in (self.scanner, self.covers):
            if w and w.isRunning():
                w.stop(); w.wait(2000)
        # Закрываем все окна чтения, чтобы сохранить позиции и статистику.
        for r in list(self.readers):
            try:
                r.close()
            except Exception:
                pass
        S.save()
        e.accept()