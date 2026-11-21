"""Окно чтения: постоянно видимая панель настройки, навигация, заметки, TTS."""
import json, re, time
from collections import OrderedDict
from PySide6.QtCore import Qt, QTimer, QUrl, QPoint, QSize, Signal
from PySide6.QtGui import (QAction, QDesktopServices, QGuiApplication, QKeySequence, QIcon,
                           QPixmap, QPainter, QColor, QFont, QPen, QShortcut)
from PySide6.QtWidgets import (QMainWindow, QDockWidget, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QListWidget, QListWidgetItem, QLineEdit, QTextBrowser, QWidget,
                               QVBoxLayout, QHBoxLayout, QLabel, QSlider, QToolBar, QMenu,
                               QMessageBox, QProgressDialog, QFileDialog, QInputDialog,
                               QApplication, QComboBox, QSpinBox, QCheckBox, QPushButton,
                               QListView, QStyledItemDelegate, QStyle, QFontComboBox, QTextEdit)

from common import S, HL, THEMES, theme, norm_theme, hms, ACCENT, PDF_LOCK
from formats import open_source, FormatError, plain
from views import ReflowView, FixedView, pick_font, chapter_text
from services import Tts, StarDict
from theming import apply_theme, chrome


def export_notes(rows, book, path):
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "json":
        open(path, "w", encoding="utf-8").write(json.dumps([dict(r) for r in rows],
                                                           ensure_ascii=False, indent=1, default=str))
        return
    out = []
    for r in rows:
        if ext == "md":
            out.append(f"> {r['text']}\n\n" + (f"*{r['note']}*\n\n" if r["note"] else "") +
                       f"— {book['title']}, гл. {r['chapter'] + 1}\n")
        elif ext == "html":
            out.append(f"<blockquote style='border-left:4px solid {r['color']};padding-left:10px'>"
                       f"{r['text']}</blockquote>" + (f"<p><i>{r['note']}</i></p>" if r["note"] else ""))
        else:
            out.append(f"«{r['text']}»" + (f"\n[{r['note']}]" if r["note"] else "") +
                       f"\n— {book['title']}, гл. {r['chapter'] + 1}\n")
    body = "\n".join(out)
    if ext == "html":
        body = f"<meta charset='utf-8'><h1>{book['title']}</h1>" + body
    open(path, "w", encoding="utf-8").write(body)


def _plain_text(s):
    return (s or "").replace("\u00ad", "")


def _raw_pos(text, plain_index):
    seen = 0
    for idx, ch in enumerate(text):
        if seen == plain_index:
            return idx
        if ch != "\u00ad":
            seen += 1
    return len(text)


class TuneBar(QWidget):
    """Постоянная панель живой настройки рендера."""
    changed = Signal(str, object)

    def __init__(self, kind, st, parent=None):
        super().__init__(parent)
        self.setObjectName("TuneBar")
        self.kind = kind
        self.st = st
        self.widgets = {}
        self._labels = []
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        root.setSpacing(12)

        def cell(label, w, key):
            if root.count():
                sep = QLabel(); sep.setObjectName("VSep"); root.addWidget(sep)
            box = QWidget(); v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3)
            lab = QLabel(label); v.addWidget(lab); v.addWidget(w)
            self._labels.append(lab)
            root.addWidget(box)
            self.widgets[key] = w
            return w

        def slider(key, lo, hi, scale=1.0):
            s = QSlider(Qt.Horizontal); s.setRange(int(lo * scale), int(hi * scale))
            s.setValue(int(float(st[key]) * scale))
            s.valueChanged.connect(lambda v, k=key, sc=scale: self.changed.emit(k, v / sc))
            return s

        def combo(key, items, data=None):
            c = QComboBox()
            for i, it in enumerate(items):
                c.addItem(str(it), data[i] if data else it)
            cur = st[key]
            idx = max(0, c.findData(cur))
            if idx < 0:
                idx = max(0, c.findText(str(cur)))
            c.setCurrentIndex(idx)
            c.currentIndexChanged.connect(lambda i, k=key, cc=c: self.changed.emit(k, cc.itemData(i)))
            return c

        if kind == "reflow":
            f = QFontComboBox(); f.setMaximumWidth(150)
            f.setCurrentFont(QFont(pick_font(st["font_family"])))
            f.currentFontChanged.connect(lambda ff: self.changed.emit("font_family", ff.family()))
            cell("Шрифт", f, "font_family")
            sp = QSpinBox(); sp.setRange(8, 40); sp.setValue(int(st["font_size"])); sp.setSuffix(" pt")
            sp.valueChanged.connect(lambda v: self.changed.emit("font_size", v))
            cell("Кегль", sp, "font_size")
            cell("Интерлиньяж", slider("line_spacing", 95, 200), "line_spacing")
            cell("Поля", slider("margin", 6, 110), "margin")
            cell("Отступ", slider("indent", 0, 56), "indent")
            cell("Колонки", combo("columns", [1, 2]), "columns")
            cell("Режим", combo("mode", ["Страницы", "Свиток"], ["paged", "scroll"]), "mode")
        else:
            cell("Подгонка", combo("pdf_fit", ["По ширине", "По странице", "Своя"],
                                   ["width", "page", "custom"]), "pdf_fit")
            sp = QSpinBox(); sp.setRange(25, 600); sp.setSingleStep(10); sp.setSuffix(" %")
            sp.setValue(int(st["pdf_zoom"]))
            sp.valueChanged.connect(lambda v: self.changed.emit("pdf_zoom", v))
            cell("Масштаб", sp, "pdf_zoom")
            cell("Зазор", slider("pdf_gap", 0, 60), "pdf_gap")
            cell("Резкость", combo("render_scale", ["Обычная", "Высокая", "Максимум"], [1.0, 1.5, 2.0]),
                 "render_scale")
            cb = QCheckBox("Обрезать поля"); cb.setChecked(bool(st["pdf_crop"]))
            cb.toggled.connect(lambda v: self.changed.emit("pdf_crop", v))
            cell("Скан", cb, "pdf_crop")
            cb2 = QCheckBox("Инверсия в ночи"); cb2.setChecked(bool(st["pdf_invert"]))
            cb2.toggled.connect(lambda v: self.changed.emit("pdf_invert", v))
            cell("Ночь", cb2, "pdf_invert")

        cell("Тема", combo("theme", list(THEMES)), "theme")
        cell("Яркость", slider("brightness", 0.55, 1.0, 100), "brightness")
        root.addStretch(1)
        reset = QPushButton("Сброс")
        reset.clicked.connect(lambda: self.changed.emit("__reset__", None))
        root.addWidget(reset, 0, Qt.AlignBottom)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = e.size().width()
        narrow = w < 980
        for lab in self._labels:
            lab.setVisible(not narrow)
        root = self.layout()
        root.setSpacing(6 if narrow else 12)
        m = 6 if narrow else 10
        root.setContentsMargins(m, 6, m, 6)
        for s in self.findChildren(QSlider):
            s.setMaximumWidth(58 if w < 700 else 92)

    def sync(self, st):
        self.st = st
        for k, w in self.widgets.items():
            if k not in st:
                continue
            w.blockSignals(True)
            try:
                if isinstance(w, QSlider):
                    sc = 100 if k == "brightness" else 1
                    w.setValue(int(float(st[k]) * sc))
                elif isinstance(w, QSpinBox):
                    w.setValue(int(st[k]))
                elif isinstance(w, QComboBox):
                    i = w.findData(st[k])
                    if i < 0:
                        i = w.findText(str(st[k]))
                    if i >= 0:
                        w.setCurrentIndex(i)
                elif isinstance(w, QCheckBox):
                    w.setChecked(bool(st[k]))
                elif isinstance(w, QFontComboBox):
                    w.setCurrentFont(QFont(pick_font(st["font_family"])))
            finally:
                w.blockSignals(False)


class ThumbDelegate(QStyledItemDelegate):
    """Миниатюры страниц: оформлены под текущую тему, выделение — акцентная рамка."""

    def __init__(self, src, parent=None):
        super().__init__(parent)
        self.src = src
        self.cache = OrderedDict()
        self._scaled = OrderedDict()
        self._theme = None
        self._c = None

    def sizeHint(self, opt, idx):
        return QSize(112, 158)

    def paint(self, p, opt, idx):
        page = idx.data(Qt.UserRole)
        if self._theme != S["theme"]:
            self._theme = S["theme"]
            self._c = chrome(theme(self._theme))
            self._scaled.clear()
        c = self._c
        r = opt.rect.adjusted(6, 6, -6, -6)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        pm = self.cache.get(page)
        if pm is None:
            try:
                with PDF_LOCK:
                    ps = self.src.page_size(page)
                    w = 96
                    h = max(8, int(w * ps.height() / max(1.0, ps.width())))
                    img = self.src.render(page, QSize(w, min(160, h)))
                pm = QPixmap.fromImage(img)
            except Exception:
                pm = QPixmap()
            self.cache[page] = pm
            while len(self.cache) > 260:
                self.cache.popitem(last=False)
        box = r.adjusted(0, 0, 0, -18)
        if not pm.isNull():
            skey = (page, int(box.width()), int(box.height()))
            s = self._scaled.get(skey)
            if s is None:
                s = pm.scaled(box.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._scaled[skey] = s
                if len(self._scaled) > 300:
                    self._scaled.popitem(last=False)
            x = box.x() + (box.width() - s.width()) // 2
            y = box.y() + (box.height() - s.height()) // 2
            p.setPen(QPen(QColor(c["shadow"]), 1))
            p.setBrush(QColor(c["field"]))
            p.drawRoundedRect(box, 5, 5)
            p.drawPixmap(x, y, s)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(c["border"]), 1))
            p.drawRoundedRect(box, 5, 5)
            if opt.state & QStyle.State_Selected:
                p.setPen(QPen(QColor(c["accent"]), 2))
                p.drawRoundedRect(box.adjusted(-2, -2, 2, 2), 5, 5)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["track"]))
            p.drawRoundedRect(box, 5, 5)
        p.setPen(QColor(c["accent"]) if opt.state & QStyle.State_Selected else QColor(c["dim"]))
        f = p.font(); f.setPointSize(8); p.setFont(f)
        p.drawText(QRect(r.x(), r.bottom() - 16, r.width(), 16), Qt.AlignCenter, str(page + 1))
        p.restore()


class Reader(QMainWindow):
    closed = Signal(object)  # уведомление библиотеки о закрытии окна

    def __init__(self, lib, row):
        super().__init__()
        self.lib, self.bid = lib, row["id"]
        self.row = lib.book(row["id"])
        self.st = dict(S)
        if self.row["rsettings"]:
            try:
                self.st.update(json.loads(self.row["rsettings"]))
            except Exception:
                pass
        self.st["theme"] = norm_theme(self.st.get("theme"))
        apply_theme(self.st["theme"], force=True)
        self.src = open_source(self.row["path"])
        self.fixed = bool(self.src.fixed)
        self.view = FixedView(self.src, self.st) if self.fixed else ReflowView(self.src, self.st)
        self.setCentralWidget(self.view)
        self.setWindowTitle(f"{self.row['title']} — LightRead")
        g = self.screen().availableGeometry()
        self.resize(min(1180, int(g.width() * 0.9)), min(860, int(g.height() * 0.9)))
        self.tts = Tts(self)
        self.tts_active = False
        self._chunks, self._ci = [], 0
        self._tts_words, self._tts_wi = [], 0
        self._tts_chunk_pos = -1
        self._tts_timer = QTimer(self); self._tts_timer.setInterval(260)
        self._tts_timer.timeout.connect(self.tts_word_tick)
        QShortcut(QKeySequence("Escape"), self, self.escape_full)
        self.t0 = time.time()
        self._pos0 = self.view.position()[1]
        self._notes = [dict(r) for r in lib.notes(self.bid)]
        self.view.notes = self._notes
        self._build()
        self.view.changed.connect(self.on_changed)
        self.view.centerTapped.connect(self.toggle_chrome)
        self.view.menuRequested.connect(self.context_menu)
        if not self.fixed:
            self.view.linkActivated.connect(self.on_link)
            self.view.fontDelta.connect(self.font_step)
        else:
            self.view.zoomChanged.connect(self.on_zoom)
        self.tts.stateChanged.connect(self.on_tts_state)
        self._save = QTimer(self); self._save.setInterval(12000)
        self._save.timeout.connect(self.save_pos); self._save.start()
        # перевёрстка тяжёлая — не делаем её на каждое движение ползунка
        self._apply_timer = QTimer(self); self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(80)
        self._apply_timer.timeout.connect(lambda: self.apply({}))
        self._auto = QTimer(self); self._auto.timeout.connect(self.autoscroll_tick)
        self._sleep = QTimer(self); self._sleep.setSingleShot(True); self._sleep.timeout.connect(self.sleep_done)
        self._clock = QTimer(self); self._clock.setInterval(20000)
        self._clock.timeout.connect(self.on_changed); self._clock.start()
        self.view.restore(self.row["chapter"], self.row["pos"])
        QTimer.singleShot(60, self.on_changed)
        self.view.setFocus()

    def _build(self):
        tb = QToolBar("Чтение"); tb.setMovable(False); self.addToolBar(tb)
        self.tb_main = tb

        def act(text, slot, sc=None, check=False):
            a = QAction(text, self)
            if sc:
                a.setShortcut(QKeySequence(sc))
            a.setCheckable(check)
            a.triggered.connect(slot)
            tb.addAction(a); self.addAction(a)
            return a

        act("Библиотека", self.close, "Ctrl+W")
        tb.addSeparator()
        act("◀ Глава", lambda: self.chapter_step(-1), "Ctrl+Left")
        act("Глава ▶", lambda: self.chapter_step(1), "Ctrl+Right")
        tb.addSeparator()
        self.a_toc = act("Содержание", self.toggle_panel, "F4", True)
        act("Поиск", lambda: self.open_panel(3), "Ctrl+F")
        act("Результат ◀", lambda: self.search_step(-1), "Shift+F3")
        act("Результат ▶", lambda: self.search_step(1), "F3")
        act("Закладка", self.add_mark, "Ctrl+B")
        act("Заметки", lambda: self.open_panel(2), "Ctrl+N")
        self.a_tts = act("Озвучка", self.tts_toggle, "Ctrl+T", True)
        self.a_auto = act("Автопрокрутка", self.auto_toggle, "Ctrl+R", True)
        tb.addSeparator()
        act("A−", lambda: self.font_step(-1), "Ctrl+-")
        act("A+", lambda: self.font_step(1), "Ctrl++")
        act("Тема", self.cycle_theme, "F5")
        self.a_tune = act("Настройка", self.toggle_tune, "F6", True)
        self.a_tune.setChecked(bool(self.st["tune_visible"]))
        self.a_full = act("Полный экран", self.fullscreen, "F11", True)
        self.a_focus = act("Фокус-режим", self.toggle_chrome, "F10", True)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self, self.quick_note)
        act("Параметры", self.settings, "F7")

        m = self.menuBar().addMenu("Книга")
        m.addAction("Сохранить настройки для этой книги", self.save_per_book)
        m.addAction("Сбросить настройки книги", self.clear_per_book)
        m.addAction("Экспорт заметок…", self.export_notes)
        m.addSeparator()
        for mins in (15, 30, 60):
            m.addAction(f"Таймер сна: {mins} мин", lambda mm=mins: self.sleep(mm))
        m.addAction("Таймер сна: выкл", lambda: self._sleep.stop())
        m.addSeparator()
        m.addAction("Информация о книге", self.info)

        self.dock = QDockWidget("Навигация", self)
        self.tabs = QTabWidget()
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName("Оглавление книги")
        self.tree.itemClicked.connect(self.toc_click)
        self.tabs.addTab(self.tree, "Содержание")
        self.marks = QListWidget(); self.marks.itemClicked.connect(self.mark_click)
        self.marks.setContextMenuPolicy(Qt.CustomContextMenu)
        self.marks.customContextMenuRequested.connect(self.mark_menu)
        self.tabs.addTab(self.marks, "Закладки")
        nw = QWidget(); nv = QVBoxLayout(nw)
        nv.setContentsMargins(4, 4, 4, 4); nv.setSpacing(5)
        self.notes = QListWidget(); self.notes.itemClicked.connect(self.note_click)
        self.notes.setAccessibleName("Заметки книги")
        self.notes.itemDoubleClicked.connect(self.note_edit_load)
        self.notes.setContextMenuPolicy(Qt.CustomContextMenu)
        self.notes.customContextMenuRequested.connect(self.note_menu)
        self.note_edit = QTextEdit()
        self.note_edit.setAccessibleName("Редактор заметки")
        self.note_edit.setPlaceholderText("Текст заметки…")
        self.note_edit.setMaximumHeight(90)
        self._edit_note_id = None
        QShortcut(QKeySequence("Ctrl+Return"), self.note_edit, self.save_note_text)
        nr = QHBoxLayout()
        save = QPushButton("Сохранить"); save.clicked.connect(self.save_note_text)
        new = QPushButton("Новая"); new.clicked.connect(self.new_note_text)
        nr.addWidget(save); nr.addWidget(new)
        nv.addWidget(self.notes, 1); nv.addWidget(self.note_edit); nv.addLayout(nr)
        self.tabs.addTab(nw, "Заметки")
        sw = QWidget(); sv = QVBoxLayout(sw)
        self.sq = QLineEdit(); self.sq.setPlaceholderText("Текст в книге…")
        self.sq.setAccessibleName("Поиск по книге")
        self.sq.returnPressed.connect(self.search)
        self._search_timer = QTimer(self); self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.search)
        self.sq.textChanged.connect(lambda _: self._search_timer.start())
        self.sres = QListWidget(); self.sres.itemClicked.connect(self.search_click)
        self.sres.setAccessibleName("Результаты поиска")
        sv.addWidget(self.sq); sv.addWidget(self.sres)
        sr = QHBoxLayout()
        self.scount = QLabel("0 совп.")
        for txt, d in (("◀", -1), ("▶", 1)):
            b = QPushButton(txt); b.setFixedWidth(34)
            b.clicked.connect(lambda _=False, dd=d: self.search_step(dd))
            sr.addWidget(b)
        sr.addWidget(self.scount, 1)
        sv.addLayout(sr)
        self.tabs.addTab(sw, "Поиск")
        dw = QWidget(); dv = QVBoxLayout(dw)
        self.dq = QLineEdit(); self.dq.setPlaceholderText("Слово…")
        self.dq.returnPressed.connect(lambda: self.lookup(self.dq.text()))
        self.dres = QTextBrowser(); self.dres.setOpenExternalLinks(True)
        dv.addWidget(self.dq); dv.addWidget(self.dres)
        self.tabs.addTab(dw, "Словарь")
        vw = QWidget(); vvl = QVBoxLayout(vw)
        self.tts_now = QLabel("Озвучка не активна"); self.tts_now.setWordWrap(True)
        self.tts_next_label = QLabel("—"); self.tts_next_label.setWordWrap(True)
        vvl.addWidget(QLabel("Сейчас читает:"))
        vvl.addWidget(self.tts_now)
        vvl.addWidget(QLabel("Далее:"))
        vvl.addWidget(self.tts_next_label)
        vvl.addStretch(1)
        self.tabs.addTab(vw, "Озвучка")
        if self.fixed:
            self.thumbs = QListView()
            self.thumbs.setViewMode(QListView.IconMode)
            self.thumbs.setResizeMode(QListView.Adjust)
            self.thumbs.setMovement(QListView.Static)
            self.thumbs.setUniformItemSizes(True)
            self.thumbs.setSpacing(2)
            from PySide6.QtGui import QStandardItemModel, QStandardItem
            tm = QStandardItemModel(self)
            for i in range(self.src.count):
                it = QStandardItem(); it.setData(i, Qt.UserRole); it.setEditable(False)
                tm.appendRow(it)
            self.thumbs.setModel(tm)
            self.thumbs.setItemDelegate(ThumbDelegate(self.src, self))
            self.thumbs.clicked.connect(lambda idx: self.view.goto(idx.data(Qt.UserRole)))
            self.tabs.addTab(self.thumbs, "Страницы")
        self.dock.setWidget(self.tabs)
        self.dock.setMinimumWidth(250)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock)
        self.dock.hide()
        self.dock.visibilityChanged.connect(lambda v: self.a_toc.setChecked(v))

        self.tune = TuneBar("pdf" if self.fixed else "reflow", self.st, self)
        self.tune.changed.connect(self.tune_changed)
        self.addToolBar(Qt.BottomToolBarArea, self._wrap_tune())
        self.tune_host.setVisible(bool(self.st["tune_visible"]))

        sb = self.statusBar()
        self.l_ch = QLabel(); self.l_pc = QLabel(); self.l_tm = QLabel()
        self.pg = QSpinBox(); self.pg.setRange(1, max(1, self.view.pages))
        self.pg.setFixedWidth(78); self.pg.valueChanged.connect(self.page_jump)
        self.l_total = QLabel(f"/ {self.view.pages}")
        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(0, 1000)
        self.slider.setMaximumWidth(300); self.slider.sliderMoved.connect(self.slider_move)
        for w in (self.l_ch, self.slider, QLabel("стр."), self.pg, self.l_total, self.l_pc, self.l_tm):
            sb.addPermanentWidget(w)
        self.fill_toc(); self.fill_marks(); self.fill_notes()

    def _wrap_tune(self):
        host = QToolBar("Настройка рендера")
        host.setMovable(False)
        host.addWidget(self.tune)
        self.tune_host = host
        return host

    def toggle_tune(self):
        vis = not self.tune_host.isVisible()
        self.tune_host.setVisible(vis)
        self.a_tune.setChecked(vis)
        self.st["tune_visible"] = vis

    def toggle_chrome(self):
        vis = not self.tb_main.isVisible()
        self.tb_main.setVisible(vis)
        self.menuBar().setVisible(vis)
        self.statusBar().setVisible(vis)
        self.tune_host.setVisible(vis and self.st["tune_visible"])
        if hasattr(self, "a_focus"):
            self.a_focus.setChecked(not vis)

    def toggle_panel(self):
        self.dock.setVisible(not self.dock.isVisible())

    def open_panel(self, i):
        self.dock.show(); self.tabs.setCurrentIndex(i)
        if i == 3:
            self.sq.setFocus()

    def fill_toc(self):
        self.tree.clear()
        parents = [self.tree.invisibleRootItem()]
        for lvl, title, ch, anchor in self.src.toc:
            while len(parents) > lvl + 1:
                parents.pop()
            while len(parents) < lvl + 1:
                parents.append(parents[-1])
            it = QTreeWidgetItem(parents[-1], [title])
            it.setData(0, Qt.UserRole, (ch, anchor))
            it.setToolTip(0, title)
            parents.append(it)
        self.tree.expandToDepth(0)

    @staticmethod
    def _page_from_anchor(anchor):
        if isinstance(anchor, (int, float)):
            return max(0, int(anchor))
        m = re.search(r"\d+", str(anchor or ""))
        return max(0, int(m.group(0)) if m else 0)

    def toc_click(self, it, _):
        ch, anchor = it.data(0, Qt.UserRole)
        if self.fixed:
            self.view.goto(self._page_from_anchor(anchor))
        else:
            if ch != self.view.ch:
                self.view.load(ch, 0)
            self.view.goto_anchor(anchor)
        self.view.setFocus()

    def fill_marks(self):
        self.marks.clear()
        for r in self.lib.marks(self.bid):
            it = QListWidgetItem(f"{r['title']}\n{(r['text'] or '')[:90]}")
            it.setData(Qt.UserRole, dict(r)); self.marks.addItem(it)

    def mark_click(self, it):
        r = it.data(Qt.UserRole)
        self.view.restore(r["chapter"], r["pos"]); self.view.setFocus()

    def mark_menu(self, pos):
        it = self.marks.itemAt(pos)
        if not it:
            return
        r = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction("Переименовать…", lambda: self.rename_mark(r))
        m.addAction("Удалить закладку", lambda: (self.lib.mark_del(r["id"]), self.fill_marks()))
        m.exec(self.marks.mapToGlobal(pos))

    def rename_mark(self, r):
        name, ok = QInputDialog.getText(self, "Закладка", "Название:", text=r["title"] or "")
        if ok and name.strip():
            self.lib.mark_upd(r["id"], title=name.strip()); self.fill_marks()

    def fill_notes(self):
        self.notes.clear()
        for r in self.lib.notes(self.bid):
            it = QListWidgetItem(f"{r['text'][:110]}" + (f"\n{r['note'][:90]}" if r["note"] else ""))
            it.setData(Qt.UserRole, dict(r))
            it.setForeground(QColor(r["color"]))
            self.notes.addItem(it)

    def note_click(self, it):
        r = it.data(Qt.UserRole)
        if self.fixed:
            self.view.goto(r["start"])
        else:
            self.view.restore(r["chapter"], r["start"])
        self.view.setFocus()

    def note_menu(self, pos):
        it = self.notes.itemAt(pos)
        if not it:
            return
        r = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction("Изменить заметку…", lambda: self.edit_note(r))
        m.addAction("Удалить", lambda: self.del_note(r))
        m.addAction("Экспорт всех…", self.export_notes)
        m.exec(self.notes.mapToGlobal(pos))

    def quick_note(self):
        self.open_panel(2)
        self.note_edit.setFocus()
        self.statusBar().showMessage("Введите заметку и нажми «Сохранить»", 3000)

    def new_note_text(self):
        self._edit_note_id = None
        self.note_edit.clear()
        self.note_edit.setFocus()

    def note_edit_load(self, it):
        r = it.data(Qt.UserRole)
        self._edit_note_id = r["id"]
        self.note_edit.setPlainText(r["note"] or "")
        self.note_edit.setFocus()

    def save_note_text(self):
        text = self.note_edit.toPlainText().strip()
        if not text:
            self.statusBar().showMessage("Введите текст заметки", 2000)
            return
        if self._edit_note_id:
            self.lib.note_upd(self._edit_note_id, note=text)
        else:
            d = self.view.add_note(HL[0], text)
            if not d:
                ch, pos = self.view.position()
                d = dict(chapter=ch, start=pos, end=pos + 1,
                         color=HL[0], text=self.view.page_text()[:160], note=text)
            self.lib.note_add(self.bid, d["chapter"], d["start"], d["end"],
                              d["color"], d["text"], text, anchor=_plain_text(d.get("text", ""))[:240])
            self._edit_note_id = None
        self.note_edit.clear()
        self.refresh_notes()
        self.statusBar().showMessage("Заметка сохранена", 2000)
        self.notify("Заметка сохранена")

    def edit_note(self, r):
        self.note_edit_load_from_row(r)

    def note_edit_load_from_row(self, r):
        self._edit_note_id = r["id"]
        self.note_edit.setPlainText(r["note"] or "")
        self.open_panel(2)
        self.note_edit.setFocus()

    def del_note(self, r):
        self.lib.note_del(r["id"]); self.refresh_notes()

    def refresh_notes(self):
        self._notes = [dict(x) for x in self.lib.notes(self.bid)]
        self.view.notes = self._notes
        if self.fixed:
            self.view.apply_notes()
            self.view.update()
        else:
            pos = self.view.position()[1]
            self.view.load(self.view.ch, pos)
            text = getattr(self.view, "_text", "")
            plain = _plain_text(text)
            for n in self._notes:
                quote = n.get("anchor")
                if not quote or n["chapter"] != self.view.ch:
                    continue
                at = plain.find(quote)
                if at < 0:
                    continue
                start, end = _raw_pos(text, at), _raw_pos(text, at + len(quote))
                if start != n["start"] or end != n["end"]:
                    n["start"], n["end"] = start, end
                    self.lib.note_upd(n["id"], start=start, end=end)
        self.fill_notes()

    def export_notes(self):
        rows = self.lib.notes(self.bid)
        if not rows:
            QMessageBox.information(self, "Экспорт", "Заметок пока нет."); return
        p, _ = QFileDialog.getSaveFileName(self, "Экспорт заметок", f"{self.row['title']}.md",
                                           "Markdown (*.md);;Текст (*.txt);;HTML (*.html);;JSON (*.json)")
        if p:
            export_notes(rows, self.row, p)
            QMessageBox.information(self, "Экспорт", f"Сохранено: {p}")

    def on_changed(self):
        ch, pos = self.view.position()
        prog = self.view.progress()
        title = self.view.chap.title if getattr(self.view, "chap", None) else self.row["title"]
        self.l_ch.setText(title[:52])
        self.pg.blockSignals(True)
        self.pg.setRange(1, max(1, self.view.pages))
        self.pg.setValue(self.view.page + 1 if self.fixed else self.view.page + 1)
        self.pg.blockSignals(False)
        self.l_total.setText(f"/ {self.view.pages}" + ("" if self.fixed else f"  гл.{ch + 1}/{self.src.count}"))
        self.l_pc.setText(f"{prog * 100:.1f}%")
        self.l_tm.setText(hms(time.time() - self.t0))
        self.slider.blockSignals(True); self.slider.setValue(int(prog * 1000)); self.slider.blockSignals(False)

    def on_zoom(self, pct):
        self.st["pdf_zoom"] = int(pct)
        self.tune.sync(self.st)

    def page_jump(self, v):
        if self.fixed:
            self.view.goto(v - 1)
        else:
            self.view.goto_pos(0)
            self.view.page = max(0, min(self.view.pages - 1, v - 1))
            self.view.update(); self.view.changed.emit()

    def slider_move(self, v):
        f = v / 1000
        if self.fixed:
            self.view.goto(int(f * self.view.count))
        else:
            ch = min(self.src.count - 1, int(f * self.src.count))
            # Не перезагружаем главу, если она уже открыта: это дёшево и дёргает
            # рендер при каждом движении ползунка.
            if ch != self.view.ch:
                self.view.load(ch, 0)
            frac = f * self.src.count - ch
            self.view.goto_pos(int(frac * max(1, len(self.view._text))))

    def save_pos(self):
        ch, pos = self.view.position()
        self.lib.set_progress(self.bid, ch, pos, self.view.progress(), self.view.pages)

    def closeEvent(self, e):
        self.save_pos()
        self.tts.stop()
        self._tts_clear()
        secs = time.time() - self.t0
        pages = 1 if self.fixed else max(0, self.view.position()[1] - self._pos0) // 1800
        self.lib.stats_add(self.bid, secs, pages)
        try:
            self.view.shutdown()
            self.src.close()
        except Exception:
            pass
        apply_theme(S["theme"], force=True)
        e.accept()
        self.closed.emit(self)

    def chapter_step(self, d):
        if self.fixed:
            (self.view.next if d > 0 else self.view.prev)(); return
        self.view.load(max(0, min(self.src.count - 1, self.view.ch + d)), 0)

    def on_link(self, href):
        if href.startswith("ext:"):
            QDesktopServices.openUrl(QUrl(href[4:])); return
        if href.startswith("go:"):
            chs, _, anchor = href[3:].partition("#")
            try:
                ch = int(chs)
            except ValueError:
                ch = self.view.ch
            if ch != self.view.ch:
                self.view.load(ch, 0)
            self.view.goto_anchor(anchor)

    def add_mark(self):
        ch, pos = self.view.position()
        title = self.view.chap.title if getattr(self.view, "chap", None) else f"Стр. {pos + 1}"
        self.lib.mark_add(self.bid, ch, pos, title, self.view.page_text()[:160].replace("\n", " "))
        self.fill_marks()
        self.statusBar().showMessage("Закладка добавлена", 2000)
        self.notify("Закладка добавлена")

    def context_menu(self, gpos):
        m = QMenu(self)
        sel = self.view.selection_text()
        if sel:
            m.addAction("Копировать", lambda: QGuiApplication.clipboard().setText(sel))
            hl = m.addMenu("Выделить цветом")
            for c in HL:
                a = QAction(c, self)
                a.triggered.connect(lambda _=False, cc=c: self.make_note(cc, ""))
                hl.addAction(a)
            m.addAction("Выделить с заметкой…", lambda: self.make_note(HL[0], None))
            m.addSeparator()
            words = sel.split()
            if words:
                m.addAction("Найти в словаре", lambda: self.lookup(words[0]))
            m.addAction("Перевести в браузере",
                        lambda: QDesktopServices.openUrl(QUrl("https://translate.google.com/?text=" + sel[:400])))
            m.addAction("Читать вслух отсюда", lambda: self.tts_from(sel))
        else:
            m.addAction("Закладка", self.add_mark)
            m.addAction("Заметка к странице…", lambda: self.make_note(HL[0], None))
            m.addAction("Поиск в книге", lambda: self.open_panel(3))
            if not self.fixed:
                m.addAction("Выделить всё и скопировать",
                            lambda: (self.view.select_all(),
                                     QGuiApplication.clipboard().setText(self.view.selection_text())))
            m.addAction("Копировать страницу",
                        lambda: QGuiApplication.clipboard().setText(self.view.page_text()))
            if self.fixed:
                m.addSeparator()
                m.addAction("По ширине", lambda: self.tune_changed("pdf_fit", "width"))
                m.addAction("По странице", lambda: self.tune_changed("pdf_fit", "page"))
                m.addAction("Обрезать поля скана",
                            lambda: self.tune_changed("pdf_crop", not self.st["pdf_crop"]))
        m.exec(gpos)

    def make_note(self, color, note):
        if note is None:
            note, ok = QInputDialog.getMultiLineText(self, "Заметка", "Комментарий:", "")
            if not ok:
                return
        d = self.view.add_note(color, note)
        if d:
            self.lib.note_add(self.bid, d["chapter"], d["start"], d["end"], color, d["text"], note,
                              anchor=_plain_text(d.get("text", ""))[:240])
            self.refresh_notes()

    def search(self):
        self._search_timer.stop()
        q = self.sq.text().strip()
        if len(q) < 2:
            return
        self.sres.clear()
        n = self.view.count if self.fixed else self.src.count
        pd = QProgressDialog("Поиск…", "Отмена", 0, n, self)
        pd.setWindowModality(Qt.WindowModal)
        hits = 0
        ql = q.lower()
        cache = getattr(self, "_plain_cache", None)
        if cache is None:
            cache = self._plain_cache = OrderedDict()
        for i in range(n):
            if i % 8 == 0:
                pd.setValue(i); QApplication.processEvents()
            if pd.wasCanceled():
                break
            if self.fixed:
                t = self.src.text(i)
            else:
                t = cache.get(i)
                if t is None:
                    t = chapter_text(self.src.chapter(i).html)
                    cache[i] = t
                    if len(cache) > 80:
                        cache.popitem(last=False)
            start = 0
            while hits < 400:
                k = t.lower().find(ql, start)
                if k < 0:
                    break
                label = f"стр. {i + 1}" if self.fixed else f"гл. {i + 1}"
                it = QListWidgetItem(f"{label}: …{t[max(0, k - 40):k + 70].strip()}…")
                it.setData(Qt.UserRole, (0 if self.fixed else i, i if self.fixed else k))
                self.sres.addItem(it)
                hits += 1; start = k + len(q)
        pd.close()
        if self.fixed and not hits:
            for _lvl, title, _ch, page in self.view.src.toc:
                if ql in (title or "").lower():
                    it = QListWidgetItem(f"Оглавление: {title}")
                    it.setData(Qt.UserRole, (0, page))
                    self.sres.addItem(it)
                    hits += 1
        self._hit_q = q
        self._hit_i = -1
        self.scount.setText(f"{hits} совп.")
        if self.fixed and not hits:
            self.statusBar().showMessage(
                "Совпадений нет: у скана может отсутствовать текстовый слой", 6000)
        else:
            self.statusBar().showMessage(f"Найдено: {hits}  (F3 / Shift+F3)", 4000)

    def search_step(self, d):
        """Переход к следующему/предыдущему совпадению (как в ReadEra)."""
        n = self.sres.count()
        if not n:
            return
        if not self.dock.isVisible() or self.tabs.currentIndex() != 3:
            self.open_panel(3)
        self._hit_i = (self._hit_i + d) % n
        it = self.sres.item(self._hit_i)
        self.sres.setCurrentItem(it)
        self.search_click(it)
        if not self.fixed:
            ch, pos = it.data(Qt.UserRole)
            if ch == self.view.ch:
                self.view.sel = (pos, pos + max(1, len(getattr(self, "_hit_q", ""))))
                self.view.update()

    def search_click(self, it):
        ch, pos = it.data(Qt.UserRole)
        if self.fixed:
            self.view.goto(self._page_from_anchor(pos))
        else:
            if ch != self.view.ch:
                self.view.load(ch, 0)
            self.view.goto_pos(pos)
        self.view.setFocus()

    def lookup(self, word):
        word = re.sub(r"[^\w\-ёЁ]", "", word or "")
        if not word:
            return
        self.open_panel(4); self.dq.setText(word)
        paths = S["dict_paths"]
        if getattr(self, "_dict", None) is None or self._dict_paths != paths:
            self._dict = StarDict(paths)
            self._dict_paths = paths
        res = self._dict.lookup(word)
        if res:
            self.dres.setHtml("<hr>".join(f"<b>{n}</b><br>{t}" for n, t in res))
        else:
            self.dres.setHtml(
                f"Словари не найдены или слово отсутствует.<br>"
                f"<a href='https://ru.wiktionary.org/wiki/{word}'>Викисловарь</a> · "
                f"<a href='https://translate.google.com/?text={word}'>Перевод</a><br><br>"
                f"<i>Папка со словарями StarDict: F7 → Сервисы.</i>")

    def _tts_clear(self):
        self._tts_timer.stop()
        self._tts_words, self._tts_wi = [], 0
        self._tts_chunk_pos = -1
        self.tts_now.setText("Озвучка не активна")
        self.tts_next_label.setText("—")
        if not self.fixed:
            self.view.sel = None
            self.view.update()

    def tts_toggle(self):
        if self.tts_active:
            self.tts_active = False; self.tts.stop(); self._tts_clear()
            self.a_tts.setChecked(False); return
        if not self.tts.ok():
            QMessageBox.warning(self, "Озвучка", "Движок TTS недоступен.")
            self.a_tts.setChecked(False); return
        self.tts.configure(self.st)
        self.tts_active = True; self.a_tts.setChecked(True)
        self.tts_feed()

    def tts_feed(self):
        self._chunks = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", self.view.page_text()) if s.strip()]
        self._ci = 0
        self.tts_next()

    def tts_from(self, text):
        if not self.tts.ok():
            return
        self.tts.configure(self.st)
        self._chunks = [text]; self._ci = 0
        self.tts_active = True; self.a_tts.setChecked(True)
        self.tts_next()

    def tts_word_tick(self):
        if self._tts_wi < len(self._tts_words):
            self._tts_wi += 1
            self._tts_labels()
            self._tts_select_word()
            word = self._tts_words[min(self._tts_wi, len(self._tts_words) - 1)]
            rate = float(self.st.get("tts_rate", 0) or 0)
            delay = (260 + max(0, len(word) - 4) * 45) / max(0.35, 1.0 + rate)
            self._tts_timer.setInterval(max(90, min(900, int(delay))))
        else:
            self._tts_timer.stop()

    def _tts_labels(self):
        words = self._tts_words
        if not words or not self.tts_active:
            self.tts_now.setText("Озвучка не активна")
            self.tts_next_label.setText("—")
            return
        i = min(self._tts_wi, len(words) - 1)
        def esc(s):
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        before = esc(" ".join(words[max(0, i - 3):i]))
        cur = esc(words[i])
        after = esc(" ".join(words[i + 1:i + 6]))
        self.tts_now.setText(f"{before} <b style='color:#7170ff'>{cur}</b> {after}".strip())
        upcoming = self._chunks[self._ci:self._ci + 2]
        self.tts_next_label.setText(" / ".join(x[:90] for x in upcoming) or "—")

    def _tts_select(self, chunk):
        if self.fixed or not chunk:
            return
        text = getattr(self.view, "_text", "")
        pos = text.find(chunk[:40])
        self._tts_chunk_pos = pos
        if pos >= 0:
            self.view.sel = (pos, min(len(text), pos + len(chunk)))
            self.view.update()

    def _tts_select_word(self):
        if self.fixed or not self._tts_words or self._tts_chunk_pos < 0:
            return
        text = getattr(self.view, "_text", "")
        idx = min(self._tts_wi, len(self._tts_words) - 1)
        offset = len(" ".join(self._tts_words[:idx]))
        pos = self._tts_chunk_pos + offset
        word = self._tts_words[idx]
        self.view.sel = (pos, min(len(text), pos + len(word)))
        self.view.update()

    def tts_next(self):
        if not self.tts_active:
            return
        if self._ci < len(self._chunks):
            chunk = self._chunks[self._ci]
            self.tts.say(chunk)
            self._ci += 1
            self._tts_words, self._tts_wi = chunk.split(), 0
            self._tts_select(chunk)
            self._tts_labels()
            self._tts_timer.start()
        elif self.st["tts_follow"] and self.view.next():
            QTimer.singleShot(220, self.tts_feed)
        else:
            self.tts_active = False; self.a_tts.setChecked(False); self._tts_clear()

    def on_tts_state(self, s):
        if "Ready" in s and self.tts_active:
            QTimer.singleShot(90, self.tts_next)

    def auto_toggle(self):
        if self._auto.isActive():
            self._auto.stop(); self.a_auto.setChecked(False)
        else:
            self.a_auto.setChecked(True)
            scroll = self.fixed or self.st["mode"] == "scroll"
            self._auto.start(60 if scroll else max(1500, int(60000 / max(5, self.st["autoscroll"]))))

    def autoscroll_tick(self):
        if self.fixed or self.st["mode"] == "scroll":
            self.view.scroll_by(max(1, self.st["autoscroll"] / 25))
        else:
            self.view.next()

    def sleep(self, mins):
        self._sleep.start(mins * 60000)
        self.statusBar().showMessage(f"Таймер сна: {mins} мин", 4000)

    def sleep_done(self):
        self.tts.stop(); self._auto.stop(); self.save_pos(); self.close()

    def font_step(self, d):
        if self.fixed:
            self.view.zoom_step(d); return
        self.st["font_size"] = max(8, min(40, int(self.st["font_size"]) + d))
        self.apply({})
        self.statusBar().showMessage(f"Кегль: {self.st['font_size']} pt", 1500)

    def cycle_theme(self):
        names = list(THEMES)
        try:
            i = names.index(self.st["theme"])
        except ValueError:
            i = 0
        self.st["theme"] = names[(i + 1) % len(names)]
        # тема общая для приложения, а не только для этой книги
        S["theme"] = self.st["theme"]
        S.save()
        apply_theme(self.st["theme"], force=True)
        self.apply({})
        self.statusBar().showMessage("Тема: " + self.st["theme"], 1500)
        self.notify("Тема: " + self.st["theme"])

    def tune_changed(self, key, value):
        if key == "__reset__":
            from common import DEFAULTS
            keys = [k for k in self.tune.widgets] + ["bold", "align", "para_space", "gap"]
            self.st.update({k: DEFAULTS[k] for k in keys if k in DEFAULTS})
            self.apply({})
            return
        self.st[key] = value
        if key == "pdf_fit" and value != "custom":
            self.view.st.update(self.st); self.view.set_fit(value)
            self.tune.sync(self.st); self.on_changed(); return
        if key == "pdf_zoom":
            self.view.st.update(self.st); self.view.set_zoom(value)
            self.tune.sync(self.st); self.on_changed(); return
        if key == "pdf_crop":
            self.view.st.update(self.st); self.view.set_crop(value)
            self.tune.sync(self.st); return
        if key == "brightness":
            # это всего лишь затемняющая заливка в paintEvent — перевёрстка не нужна
            self.view.st.update(self.st); self.view.update()
            self.tune.sync(self.st); return
        if key == "theme":
            S["theme"] = value; S.save()
            apply_theme(value, force=True)
            self.view.st.update(self.st)
            if not self.fixed:
                self.view.restyle()
            self.tune.sync(self.st); return
        if key == "pdf_gap":
            self.view.st.update(self.st); self.view._relayout()
            self.tune.sync(self.st); return
        if key == "render_scale":
            self.view.st.update(self.st); self.view.restyle()
            self.tune.sync(self.st); return
        self._apply_timer.start()

    def apply(self, d):
        self.st.update(d)
        apply_theme(self.st["theme"])
        self.view.st.update(self.st)
        self.view.restyle()
        self.tts.configure(self.st)
        self.tune.sync(self.st)
        self.on_changed()

    def settings(self):
        from ui import SettingsDialog
        dlg = SettingsDialog(dict(self.st), self)
        if dlg.exec():
            self.st.update(dlg.s)
            S.update({k: v for k, v in self.st.items() if k in S})
            S.save()
            self.apply({})
            if S["save_per_book"]:
                self.save_per_book()

    def save_per_book(self):
        keys = ("font_family", "font_size", "bold", "line_spacing", "indent", "para_space", "align",
                "margin", "gap", "columns", "mode", "theme", "brightness", "pdf_invert",
                "pdf_fit", "pdf_zoom", "pdf_crop", "pdf_gap", "render_scale")
        self.lib.set_field(self.bid, rsettings=json.dumps({k: self.st[k] for k in keys}, ensure_ascii=False))
        self.statusBar().showMessage("Настройки сохранены для этой книги", 2500)

    def clear_per_book(self):
        self.lib.set_field(self.bid, rsettings="")
        self.apply(dict(S))

    def fullscreen(self):
        main = self.window()
        if main is not self and hasattr(main, "reader_fullscreen"):
            main.reader_fullscreen(self)
            self.a_full.setChecked(getattr(main, "_reading_full", False))
            return
        if self.isFullScreen():
            self.showNormal(); self.a_full.setChecked(False)
        else:
            self.showFullScreen(); self.a_full.setChecked(True)

    def notify(self, text):
        win = self.window()
        if win is not self and hasattr(win, "notify"):
            win.notify(text)

    def escape_full(self):
        main = self.window()
        if getattr(main, "_reading_full", False) or self.isFullScreen():
            self.fullscreen()

    def info(self):
        r = self.lib.book(self.bid)
        QMessageBox.information(self, "О книге",
                                f"{r['title']}\n\nАвтор: {r['author'] or '—'}\n"
                                f"Серия: {r['series'] or '—'}\nФормат: {r['fmt'].upper()}\n"
                                f"Прогресс: {r['progress'] * 100:.1f}%\n"
                                f"Время чтения: {hms(r['seconds'])}\nФайл: {r['path']}\n\n"
                                f"{(r['annotation'] or '')[:900]}")