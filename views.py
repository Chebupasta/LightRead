"""Рендер: ReflowView (EPUB/FB2/…) и FixedView (PDF/DjVu) с непрерывной прокруткой,
HiDPI-рендером в фоне, обрезкой полей сканов и стабильным масштабом."""
from __future__ import annotations
import statistics, threading, functools
from collections import OrderedDict

from PySide6.QtCore import (Qt, QPoint, QPointF, QRectF, QSize, QSizeF, QUrl, QTimer,
                            QThread, QObject, Signal)
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap, QPen,
                           QTextCharFormat, QTextCursor, QTextBlockFormat, QTextDocument)
from PySide6.QtWidgets import QWidget, QScrollBar

from common import theme, PDF_LOCK


@functools.lru_cache(maxsize=None)
def pick_font(pref=""):
    fams = set(QFontDatabase.families())
    if pref and pref in fams:
        return pref
    for f in ("Literata", "Charter", "Georgia", "PT Serif", "Noto Serif",
              "Liberation Serif", "DejaVu Serif", "Times New Roman"):
        if f in fams:
            return f
    return QFont().family()


def pdf_page_size(doc, i):
    for name in ("pagePointSize", "pageSize"):
        fn = getattr(doc, name, None)
        if fn is None:
            continue
        try:
            s = fn(i)
            if s is not None and not s.isEmpty():
                return QSizeF(s)
        except Exception:
            continue
    return QSizeF(595.0, 842.0)


def _render_opts():
    from PySide6.QtPdf import QPdfDocumentRenderOptions
    o = QPdfDocumentRenderOptions()
    try:
        F = QPdfDocumentRenderOptions.RenderFlag
        o.setRenderFlags(F.Annotations | F.FormFields)
    except Exception:
        pass
    return o


def detect_crop(img):
    """Поля скана → доли страницы (быстро, на сером мини-рендере)."""
    try:
        g = img.convertToFormat(QImage.Format_Grayscale8)
        w, h, bpl = g.width(), g.height(), g.bytesPerLine()
        if w < 8 or h < 8:
            return QRectF(0, 0, 1, 1)
        buf = bytes(g.constBits())
        thr = 244
        rows = [y for y in range(h) if min(buf[y * bpl: y * bpl + w]) < thr]
        cols = [x for x in range(w) if min(buf[x: (h - 1) * bpl + x + 1: bpl]) < thr]
        if not rows or not cols:
            return QRectF(0, 0, 1, 1)
        pad = 0.012
        x0 = max(0.0, cols[0] / w - pad)
        x1 = min(1.0, (cols[-1] + 1) / w + pad)
        y0 = max(0.0, rows[0] / h - pad)
        y1 = min(1.0, (rows[-1] + 1) / h + pad)
        if x1 - x0 < 0.25 or y1 - y0 < 0.25:
            return QRectF(0, 0, 1, 1)
        return QRectF(x0, y0, x1 - x0, y1 - y0)
    except Exception:
        return QRectF(0, 0, 1, 1)


class _PdfWorker(QThread):
    rendered = Signal(object, object)
    cropFound = Signal(int, object)

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        self._stop = False

    def stop(self):
        self._stop = True
        self.e.wake()

    def run(self):
        from PySide6.QtPdf import QPdfDocument
        doc = QPdfDocument()
        with PDF_LOCK:
            ok = doc.load(self.e.path)
        try:
            from PySide6.QtPdf import QPdfDocument as D
            if ok != D.Error.None_:
                return
        except Exception:
            pass
        opts = _render_opts()
        while not self._stop:
            job = self.e.take()
            if job is None:
                self.msleep(6)
                continue
            kind, page, key, w, h, invert, gen = job
            if gen != self.e.gen:
                continue
            with PDF_LOCK:
                if self._stop:
                    break
                img = doc.render(page, QSize(max(1, w), max(1, h)), opts)
            if img.isNull():
                continue
            if kind == "crop":
                self.cropFound.emit(page, detect_crop(img))
                continue
            if invert:
                try:
                    img.invertPixels(QImage.InvertRgb)
                except Exception:
                    pass
            self.rendered.emit(key, img)


class PdfEngine(QObject):
    """Очередь рендера + кэш пикселей с бюджетом памяти."""
    ready = Signal(object)
    cropped = Signal(int)

    def __init__(self, src, parent=None):
        super().__init__(parent)
        self.src = src
        self.path = str(getattr(src, "path", "") or "")
        with PDF_LOCK:
            self.sizes = [pdf_page_size(src.doc, i) for i in range(max(0, src.count))]
        if not self.sizes:
            self.sizes = [QSizeF(595, 842)]
        ws = [s.width() for s in self.sizes]
        hs = [s.height() for s in self.sizes]
        self.med_w = statistics.median(ws) or 595.0
        self.med_h = statistics.median(hs) or 842.0
        self.crop = {}
        self.cache = OrderedDict()
        self.pixels = 0
        self.budget = 110 * 1024 * 1024
        self.gen = 0
        self._jobs = []
        self._lock = threading.Lock()
        self._worker = None

    def start(self):
        if self._worker is None and self.path:
            self._worker = _PdfWorker(self)
            self._worker.rendered.connect(self._on_render)
            self._worker.cropFound.connect(self._on_crop)
            self._worker.start()

    def wake(self):
        with self._lock:
            pass

    def take(self):
        with self._lock:
            return self._jobs.pop(0) if self._jobs else None

    def invalidate(self):
        self.gen += 1
        with self._lock:
            self._jobs.clear()

    def drop_cache(self):
        self.cache.clear()
        self.pixels = 0

    def has(self, key):
        return key in self.cache

    def get(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def request(self, page, w, h, invert, crop_on, front=False):
        key = (page, int(w), int(h), bool(invert), bool(crop_on), self.gen)
        if key in self.cache:
            return key
        job = ("page", page, key, int(w), int(h), bool(invert), self.gen)
        with self._lock:
            if any(j[2] == key for j in self._jobs):
                return key
            if front:
                self._jobs.insert(0, job)
            else:
                self._jobs.append(job)
            if len(self._jobs) > 24:
                del self._jobs[12:]
        return key

    def request_crop(self, page):
        if page in self.crop:
            return
        with self._lock:
            if any(j[0] == "crop" and j[1] == page for j in self._jobs):
                return
            self._jobs.insert(0, ("crop", page, None, 200, 280, False, self.gen))

    def sync_render(self, page, w, h, invert):
        """Запасной путь, если фоновый документ недоступен."""
        with PDF_LOCK:
            img = self.src.render(page, QSize(max(1, int(w)), max(1, int(h))))
        if invert and not img.isNull():
            try:
                img.invertPixels(QImage.InvertRgb)
            except Exception:
                pass
        return img

    def _on_render(self, key, img):
        if key[5] != self.gen:
            return
        px = img.width() * img.height()
        self.cache[key] = img
        self.pixels += px
        while self.pixels > self.budget and len(self.cache) > 2:
            _, old = self.cache.popitem(last=False)
            self.pixels -= old.width() * old.height()
        self.ready.emit(key)

    def _on_crop(self, page, rect):
        self.crop[page] = rect
        self.cropped.emit(page)

    def shutdown(self):
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(1500)
            self._worker = None
        self.drop_cache()


class BookDoc(QTextDocument):
    def __init__(self, src, parent=None):
        super().__init__(parent)
        self.src = src

    def loadResource(self, rtype, url):
        if int(rtype) == int(QTextDocument.ImageResource):
            data = self.src.resource(url.toString())
            if data:
                img = QImage.fromData(data)
                if not img.isNull():
                    return img
            return QImage()
        return super().loadResource(rtype, url)


class ReflowView(QWidget):
    changed = Signal()
    menuRequested = Signal(QPoint)
    centerTapped = Signal()
    linkActivated = Signal(str)
    fontDelta = Signal(int)

    def __init__(self, src, st, parent=None):
        super().__init__(parent)
        self.src, self.st = src, dict(st)
        self.doc = BookDoc(src, self)
        self.doc.setDocumentMargin(0)
        self.ch = 0; self.page = 0; self.off = 0.0
        self.pages = 1; self.total = 0.0
        self.notes = []; self.sel = None
        self._drag = None; self._text = ""; self.chap = None
        self._chap_cache = OrderedDict()  # не парсим ZIP/XML заново при возврате к главе
        self._restyle_timer = QTimer(self); self._restyle_timer.setSingleShot(True)
        self._restyle_timer.setInterval(120)
        self._restyle_timer.timeout.connect(lambda: self.restyle())
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(260, 200)

    def shutdown(self):
        pass

    def ncols(self):
        return 2 if (int(self.st["columns"]) == 2 and self.st["mode"] == "paged") else 1

    def content(self):
        m = float(self.st["margin"])
        return QRectF(m, m, max(60, self.width() - 2 * m), max(60, self.height() - 2 * m))

    def colw(self):
        c, n = self.content(), self.ncols()
        g = float(self.st["gap"]) if n > 1 else 0
        return max(60, (c.width() - g * (n - 1)) / n)

    def colrect(self, k):
        c, w = self.content(), self.colw()
        return QRectF(c.x() + k * (w + self.st["gap"]), c.y(), w, c.height())

    def page_h(self):
        return self.content().height()

    def offset_of(self, k):
        return self.off if self.st["mode"] == "scroll" else (self.page + k) * self.page_h()

    def doc_point(self, pt):
        for k in range(self.ncols()):
            r = self.colrect(k)
            if r.contains(pt) or k == self.ncols() - 1:
                x = min(max(0.0, pt.x() - r.x()), r.width() - 1)
                return QPointF(x, pt.y() - r.y() + self.offset_of(k))
        return QPointF(0, 0)

    def load(self, ch, pos=0):
        ch = max(0, min(self.src.count - 1, int(ch)))
        if ch in self._chap_cache:
            self.chap = self._chap_cache.pop(ch)
            self._chap_cache[ch] = self.chap
        else:
            self.chap = self.src.chapter(ch)
            self._chap_cache[ch] = self.chap
            if len(self._chap_cache) > 12:
                self._chap_cache.popitem(last=False)
        self.ch = ch
        self.doc.setHtml("<body>" + self.chap.html + "</body>")
        self._text = self.doc.toPlainText()
        self.restyle(pos)

    def restyle(self, pos=None):
        if self.chap is None:
            return
        if pos is None:
            pos = self.position()[1]
        st = self.st
        th = theme(st["theme"])
        f = QFont(pick_font(st["font_family"]), int(st["font_size"]))
        f.setWeight(QFont.DemiBold if st["bold"] else QFont.Normal)
        f.setHintingPreference(QFont.PreferFullHinting)
        self.doc.setDefaultFont(f)
        self.doc.setDefaultStyleSheet(
            f"body{{color:{th['fg']};}} a{{color:{th['link']};text-decoration:none;}} "
            f"h1,h2,h3,h4,h5,h6{{color:{th['fg']};}}")
        cur = QTextCursor(self.doc)
        cur.select(QTextCursor.Document)
        bf = QTextBlockFormat()
        # В PySide6 6.11 LineHeightTypes — enum, который нельзя привести через int().
        # Берём целое значение явно (совместимо и со старыми версиями).
        prop_height = getattr(QTextBlockFormat.ProportionalHeight, "value",
                              QTextBlockFormat.ProportionalHeight)
        bf.setLineHeight(float(st["line_spacing"]), int(prop_height))
        bf.setTextIndent(float(st["indent"]))
        bf.setTopMargin(float(st["para_space"]))
        bf.setBottomMargin(0.0)
        bf.setAlignment(Qt.AlignJustify if st["align"] == "justify" else Qt.AlignLeft)
        cur.mergeBlockFormat(bf)

        b = self.doc.begin()
        while b.isValid():
            fmt = b.blockFormat()
            if fmt.headingLevel() or b.textList() is not None:
                fix = QTextBlockFormat()
                fix.setTextIndent(0.0)
                fix.setAlignment(Qt.AlignLeft)
                if fmt.headingLevel():
                    fix.setTopMargin(16.0); fix.setBottomMargin(9.0)
                QTextCursor(b).mergeBlockFormat(fix)
            it = b.begin()
            while not it.atEnd():
                fr = it.fragment(); cf = fr.charFormat()
                if cf.isImageFormat():
                    imf = cf.toImageFormat()
                    res = self.doc.resource(int(QTextDocument.ImageResource), QUrl(imf.name()))
                    w, h = imf.width(), imf.height()
                    if isinstance(res, QImage) and not res.isNull() and (w <= 0 or h <= 0):
                        w, h = res.width(), res.height()
                    maxw = max(20.0, self.colw() - 2)
                    maxh = max(20.0, self.page_h() * 0.94)
                    if w > 0 and h > 0:
                        k = min(1.0, maxw / w, maxh / h)
                        imf.setWidth(w * k); imf.setHeight(h * k)
                        c3 = QTextCursor(self.doc)
                        c3.setPosition(fr.position())
                        c3.setPosition(fr.position() + 1, QTextCursor.KeepAnchor)
                        c3.mergeCharFormat(imf)
                it += 1
            b = b.next()

        cw = self.colw()
        if st["mode"] == "scroll":
            self.doc.setPageSize(QSizeF(cw, 1e6))
            self.pages = 1
            self.total = self.doc.documentLayout().documentSize().height()
        else:
            self.doc.setPageSize(QSizeF(cw, self.page_h()))
            self.pages = max(1, self.doc.pageCount())
            self.total = self.pages * self.page_h()
        self.apply_notes()
        self.sel = None
        self.goto_pos(pos)

    def apply_notes(self):
        for n in self.notes:
            if n["chapter"] != self.ch:
                continue
            c = QTextCursor(self.doc)
            c.setPosition(max(0, int(n["start"])))
            c.setPosition(min(len(self._text), int(n["end"])), QTextCursor.KeepAnchor)
            fmt = QTextCharFormat()
            col = QColor(n["color"]); col.setAlpha(105)
            fmt.setBackground(col)
            if n["note"]:
                fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
                fmt.setUnderlineColor(QColor(n["color"]))
            c.mergeCharFormat(fmt)

    def y_for_pos(self, pos):
        c = QTextCursor(self.doc)
        c.setPosition(max(0, min(len(self._text), int(pos))))
        blk = c.block(); lay = blk.layout()
        line = lay.lineForTextPosition(c.positionInBlock())
        top = self.doc.documentLayout().blockBoundingRect(blk).top()
        return top + (line.y() if line.isValid() else 0)

    def pos_at_y(self, y):
        return self.doc.documentLayout().hitTest(QPointF(2, max(0, y) + 2), Qt.FuzzyHit)

    def goto_pos(self, pos):
        y = self.y_for_pos(pos)
        if self.st["mode"] == "scroll":
            self.off = max(0.0, min(y, max(0.0, self.total - self.page_h())))
        else:
            # В режиме двух колонок page — это номер разворота, а не
            # физической страницы: выравниваем позицию на начало разворота.
            n = self.ncols()
            p = int(y // self.page_h())
            self.page = max(0, min(self.pages - 1, (p // n) * n))
        self.update(); self.changed.emit()

    def position(self):
        return self.ch, self.pos_at_y(self.offset_of(0))

    def progress(self):
        frac = min(1.0, self.position()[1] / max(1, len(self._text)))
        return (self.ch + frac) / max(1, self.src.count)

    def restore(self, ch, pos):
        self.load(ch, pos)

    def goto_anchor(self, anchor):
        if isinstance(anchor, int):
            self.goto_pos(anchor); return
        # Content, собранное по заголовкам (DOCX/ODT/HTML), ссылается прямо
        # на смещение в тексте: pos:123.
        if isinstance(anchor, str) and anchor.startswith("pos:"):
            try:
                self.goto_pos(int(anchor[4:])); return
            except ValueError:
                pass
        pos = (self.chap.anchors or {}).get(anchor) if self.chap else None
        if pos is None and anchor:
            pos = self.doc.find(anchor).selectionStart()
        self.goto_pos(pos or 0)

    def next(self):
        if self.st["mode"] == "scroll":
            step = self.page_h() * 0.92
            if self.off + step < self.total - self.page_h():
                self.off += step; self.update(); self.changed.emit(); return True
            self.off = max(0.0, self.total - self.page_h())
        elif self.page + self.ncols() < self.pages:
            self.page += self.ncols(); self.update(); self.changed.emit(); return True
        if self.ch + 1 < self.src.count:
            self.load(self.ch + 1, 0); return True
        self.update(); self.changed.emit(); return False

    def prev(self):
        if self.st["mode"] == "scroll":
            if self.off > 0:
                self.off = max(0.0, self.off - self.page_h() * 0.92)
                self.update(); self.changed.emit(); return True
        elif self.page > 0:
            self.page = max(0, self.page - self.ncols())
            self.update(); self.changed.emit(); return True
        if self.ch > 0:
            self.load(self.ch - 1, 0)
            if self.st["mode"] == "scroll":
                self.off = max(0.0, self.total - self.page_h())
            else:
                self.page = max(0, self.pages - self.ncols())
            self.update(); self.changed.emit(); return True
        return False

    def first(self): self.load(0, 0)

    def last(self):
        self.load(self.src.count - 1, 0)
        if self.st["mode"] == "scroll":
            self.off = max(0.0, self.total - self.page_h())
        else:
            self.page = max(0, self.pages - self.ncols())
        self.update(); self.changed.emit()

    def scroll_by(self, px):
        if self.st["mode"] == "scroll":
            self.off = max(0.0, min(self.off + px, max(0.0, self.total - self.page_h())))
            self.update(); self.changed.emit()
        else:
            (self.next if px > 0 else self.prev)()

    def page_text(self):
        a = self.pos_at_y(self.offset_of(0))
        b = self.pos_at_y(self.offset_of(0) + self.page_h()) if self.st["mode"] == "scroll" \
            else self.pos_at_y((self.page + self.ncols()) * self.page_h())
        if b <= a:
            b = len(self._text)
        return self._text[a:b].replace("\ufffc", " ").replace("\u2029", "\n").replace("\u2028", "\n")

    def selection_text(self):
        if not self.sel:
            return ""
        s, e = sorted(self.sel)
        return self._text[s:e].replace("\u2029", "\n")

    def select_word(self, pos):
        c = QTextCursor(self.doc); c.setPosition(pos); c.select(QTextCursor.WordUnderCursor)
        self.sel = (c.selectionStart(), c.selectionEnd()); self.update()

    def select_all(self):
        self.sel = (0, len(self._text)); self.update()

    def add_note(self, color, note=""):
        if not self.sel:
            return None
        s, e = sorted(self.sel)
        if e - s < 1:
            return None
        return dict(chapter=self.ch, start=s, end=e, color=color, text=self._text[s:e], note=note)

    def _sel_rects(self):
        if not self.sel:
            return []
        s, e = sorted(self.sel)
        out = []
        blk = self.doc.findBlock(s)
        while blk.isValid() and blk.position() <= e:
            lay = blk.layout()
            base = self.doc.documentLayout().blockBoundingRect(blk).topLeft()
            for i in range(lay.lineCount()):
                line = lay.lineAt(i)
                ls = blk.position() + line.textStart()
                le = ls + line.textLength()
                a, b = max(s, ls), min(e, le)
                if b > a:
                    try:
                        x1 = line.cursorToX(a - blk.position())
                        x2 = line.cursorToX(b - blk.position())
                        x1 = x1[0] if isinstance(x1, tuple) else x1
                        x2 = x2[0] if isinstance(x2, tuple) else x2
                    except Exception:
                        continue
                    out.append(QRectF(base.x() + min(x1, x2), base.y() + line.y(),
                                      abs(x2 - x1), line.height()))
            blk = blk.next()
        return out

    def paintEvent(self, _):
        th = theme(self.st["theme"])
        p = QPainter(self)
        try:
            p.fillRect(self.rect(), QColor(th["desk"]))
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setRenderHint(QPainter.TextAntialiasing, True)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            c = self.content()
            p.fillRect(c, QColor(th["bg"]))
            sel = QColor(th["sel"]); sel.setAlpha(150)
            for k in range(self.ncols()):
                r, off = self.colrect(k), self.offset_of(k)
                if self.st["mode"] == "paged" and self.page + k >= self.pages:
                    continue
                p.save()
                p.setClipRect(r)
                p.translate(r.x(), r.y() - off)
                self.doc.drawContents(p, QRectF(0, off, r.width(), r.height()))
                p.setPen(Qt.NoPen); p.setBrush(sel)
                for sr in self._sel_rects():
                    if sr.bottom() >= off and sr.top() <= off + r.height():
                        p.drawRect(sr)
                p.restore()
            if self.st["brightness"] < 1.0:
                p.fillRect(self.rect(), QColor(0, 0, 0, int((1 - self.st["brightness"]) * 205)))
        finally:
            p.end()

    def resizeEvent(self, _):
        if self.chap is not None:
            self._restyle_timer.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = self.doc.documentLayout().hitTest(self.doc_point(e.position()), Qt.FuzzyHit)
            self._drag = (pos, pos, e.position())
            self.sel = None; self.update()
        elif e.button() == Qt.BackButton:
            self.prev()
        elif e.button() == Qt.RightButton:
            self.menuRequested.emit(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self._drag:
            pos = self.doc.documentLayout().hitTest(self.doc_point(e.position()), Qt.FuzzyHit)
            self._drag = (self._drag[0], pos, self._drag[2])
            if pos != self._drag[0]:
                self.sel = (self._drag[0], pos)
            self.update()
        else:
            anchor = ""
            for k in range(self.ncols()):
                if self.colrect(k).contains(e.position()):
                    anchor = self.doc.documentLayout().anchorAt(self.doc_point(e.position()))
            self.setCursor(Qt.PointingHandCursor if anchor else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._drag:
            return
        start, end, origin = self._drag
        self._drag = None
        if (e.position() - origin).manhattanLength() > 6 and start != end:
            self.sel = (min(start, end), max(start, end))
            self.update(); self.menuRequested.emit(e.globalPosition().toPoint()); return
        for k in range(self.ncols()):
            if self.colrect(k).contains(e.position()):
                anchor = self.doc.documentLayout().anchorAt(self.doc_point(e.position()))
                if anchor:
                    self.linkActivated.emit(anchor); return
        if not self.st["tap_zones"]:
            self.next(); return
        x = e.position().x() / max(1, self.width())
        if x < 0.28: self.prev()
        elif x > 0.72: self.next()
        else: self.centerTapped.emit()

    def mouseDoubleClickEvent(self, e):
        self.select_word(self.doc.documentLayout().hitTest(self.doc_point(e.position()), Qt.FuzzyHit))
        self.menuRequested.emit(e.globalPosition().toPoint())

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.fontDelta.emit(1 if e.angleDelta().y() > 0 else -1); return
        dy = e.angleDelta().y()
        if self.st["mode"] == "scroll":
            self.scroll_by(-dy * 0.65)
        elif self.st["wheel_pages"]:
            (self.prev if dy > 0 else self.next)()
        else:
            self.scroll_by(-dy)

    def keyPressEvent(self, e):
        k, mod = e.key(), e.modifiers()
        if k in (Qt.Key_PageDown, Qt.Key_Space, Qt.Key_Right, Qt.Key_Down): self.next()
        elif k in (Qt.Key_PageUp, Qt.Key_Backspace, Qt.Key_Left, Qt.Key_Up): self.prev()
        elif k == Qt.Key_Home: self.first()
        elif k == Qt.Key_End: self.last()
        elif k == Qt.Key_C and mod & Qt.ControlModifier and self.sel:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(self.selection_text())
        else:
            super().keyPressEvent(e)


PagedView = ReflowView


class FixedView(QWidget):
    """PDF/DjVu: непрерывная прокрутка, фоновый HiDPI-рендер, обрезка полей."""
    changed = Signal()
    menuRequested = Signal(QPoint)
    centerTapped = Signal()
    zoomChanged = Signal(float)

    def __init__(self, src, st, parent=None):
        super().__init__(parent)
        self.src, self.st = src, dict(st)
        self.count = max(1, src.count)
        self.engine = PdfEngine(src, self)
        self.engine.ready.connect(self._on_ready)
        self.engine.cropped.connect(lambda _p: self._relayout())
        self.engine.start()
        self.chap = None
        self.notes = []
        self.page = 0
        self.scale = 1.0
        self.ox = 0.0; self.oy = 0.0
        self._tx = 0.0; self._ty = 0.0
        self._layout = []
        self.total = 0.0; self.docw = 0.0
        self._drag = None
        self._pix = {}
        self.vbar = QScrollBar(Qt.Vertical, self)
        self.hbar = QScrollBar(Qt.Horizontal, self)
        self.vbar.valueChanged.connect(self._vbar)
        self.hbar.valueChanged.connect(self._hbar)
        self._anim = QTimer(self); self._anim.setInterval(16); self._anim.timeout.connect(self._tick)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(260, 200)
        QTimer.singleShot(0, self._apply_fit)

    def shutdown(self):
        self._anim.stop()
        self.engine.shutdown()

    # ── масштаб ──
    def _view_w(self):
        return max(80, self.width() - (self.vbar.width() if self.vbar.isVisible() else 12))

    def _apply_fit(self, anchor=None):
        g = float(self.st["pdf_gap"])
        vw = self._view_w() - 2 * g
        vh = self.height() - 2 * g
        fit = self.st["pdf_fit"]
        if fit == "width":
            s = vw / self.engine.med_w
        elif fit == "page":
            s = min(vw / self.engine.med_w, vh / self.engine.med_h)
        else:
            s = float(self.st["pdf_zoom"]) / 100.0
        s = max(0.05, min(8.0, s))
        if abs(s - self.scale) < 1e-6:
            self._relayout(); return
        cx = (self.ox + self.width() / 2) / max(1e-6, self.scale)
        cy = (self.oy + self.height() / 2) / max(1e-6, self.scale)
        if anchor is not None:
            cx, cy = anchor
        self.scale = s
        self.engine.invalidate()
        self._relayout()
        self._tx = max(0.0, cx * s - self.width() / 2)
        self._ty = max(0.0, cy * s - self.height() / 2)
        self.ox, self.oy = self._tx, self._ty
        self._sync_bars(); self.update()
        self.zoomChanged.emit(self.scale * 100)
        self.changed.emit()

    def set_fit(self, mode):
        self.st["pdf_fit"] = mode
        self._apply_fit()

    def set_zoom(self, pct):
        self.st["pdf_fit"] = "custom"
        self.st["pdf_zoom"] = max(25, min(600, int(pct)))
        self._apply_fit()

    def zoom_step(self, d, anchor=None):
        self.set_zoom(self.scale * 100 * (1.18 if d > 0 else 1 / 1.18))

    def set_crop(self, on):
        self.st["pdf_crop"] = bool(on)
        self.engine.invalidate()
        self._relayout()

    def restyle(self, *_):
        self.engine.invalidate()
        self._pix.clear()
        self._apply_fit()

    # ── раскладка ──
    def _relayout(self):
        g = float(self.st["pdf_gap"])
        vw = self._view_w()
        crop_on = bool(self.st["pdf_crop"])
        self._layout = []
        y = g
        maxw = 0.0
        top_lim = self.oy - 240.0
        bot_lim = self.oy + self.height() + 240.0
        for i, ps in enumerate(self.engine.sizes):
            cr = self.engine.crop.get(i) if crop_on else None
            fw = cr.width() if cr else 1.0
            fh = cr.height() if cr else 1.0
            w = max(8.0, ps.width() * fw * self.scale)
            h = max(8.0, ps.height() * fh * self.scale)
            x = max(g, (vw - w) / 2.0)
            rect = QRectF(x, y, w, h)
            self._layout.append(rect)
            if crop_on and cr is None and rect.bottom() >= top_lim and rect.top() <= bot_lim:
                self.engine.request_crop(i)
            maxw = max(maxw, w + 2 * g)
            y += h + g
        self.total = y
        self.docw = max(vw, maxw)
        self._sync_bars()
        self.update()

    def _sync_bars(self):
        vh = self.height(); vw = self.width()
        vmax = max(0, int(self.total - vh))
        self.vbar.blockSignals(True)
        self.vbar.setRange(0, vmax)
        self.vbar.setPageStep(max(1, int(vh * 0.9)))
        self.vbar.setSingleStep(48)
        self.vbar.setValue(int(min(self.oy, vmax)))
        self.vbar.blockSignals(False)
        self.vbar.setVisible(vmax > 0)
        hmax = max(0, int(self.docw - vw))
        self.hbar.blockSignals(True)
        self.hbar.setRange(0, hmax)
        self.hbar.setPageStep(max(1, int(vw * 0.9)))
        self.hbar.setValue(int(min(self.ox, hmax)))
        self.hbar.blockSignals(False)
        self.hbar.setVisible(hmax > 0)
        self._place_bars()

    def _place_bars(self):
        w, h = self.width(), self.height()
        bw = 12
        self.vbar.setGeometry(w - bw - 2, 2, bw, h - 4)
        self.hbar.setGeometry(2, h - bw - 2, w - 4 - (bw if self.vbar.isVisible() else 0), bw)

    def _vbar(self, v):
        self._ty = float(v); self.oy = float(v); self._update_page(); self.update()

    def _hbar(self, v):
        self._tx = float(v); self.ox = float(v); self.update()

    def _tick(self):
        dx, dy = self._tx - self.ox, self._ty - self.oy
        if abs(dx) < 0.6 and abs(dy) < 0.6:
            self.ox, self.oy = self._tx, self._ty
            self._anim.stop()
        else:
            self.ox += dx * 0.28
            self.oy += dy * 0.28
        self._sync_bars(); self._update_page(); self.update()

    def _scroll_to(self, x, y, smooth=True):
        self._tx = max(0.0, min(x, max(0.0, self.docw - self.width())))
        self._ty = max(0.0, min(y, max(0.0, self.total - self.height())))
        if smooth and not self._anim.isActive():
            self._anim.start()
        elif not smooth:
            self.ox, self.oy = self._tx, self._ty
            self._sync_bars(); self._update_page(); self.update()

    def _update_page(self):
        if not self._layout:
            return
        mid = self.oy + self.height() * 0.4
        best, bestd = 0, 1e18
        for i, r in enumerate(self._layout):
            if r.top() <= mid <= r.bottom():
                best = i
                break
            d = abs(r.center().y() - mid)
            if d < bestd:
                best, bestd = i, d
        if best != self.page:
            self.page = best
            self.changed.emit()

    # ── совместимый API ──
    @property
    def pages(self): return self.count
    @property
    def ch(self): return 0

    def load(self, ch, pos=0): self.goto(int(pos))
    def restore(self, ch, pos): self.goto(int(pos))
    def goto_anchor(self, a): self.goto(int(a or 0))
    def apply_notes(self): pass
    def selection_text(self): return ""
    def page_text(self): return self.src.text(self.page)

    def goto(self, p):
        p = max(0, min(self.count - 1, int(p)))
        self.page = p
        if not self._layout:
            self._relayout()
        if p < len(self._layout):
            self._scroll_to(self.ox, self._layout[p].top() - float(self.st["pdf_gap"]))
        self.changed.emit()

    def position(self): return 0, self.page
    def progress(self): return (self.page + 1) / self.count
    def next(self):
        if self.page + 1 < self.count:
            self.goto(self.page + 1); return True
        return False
    def prev(self):
        if self.page > 0:
            self.goto(self.page - 1); return True
        return False
    def first(self): self.goto(0)
    def last(self): self.goto(self.count - 1)
    def scroll_by(self, px): self._scroll_to(self._tx, self._ty + px)

    # ── рендер ──
    def _on_ready(self, key):
        self._pix.pop(key, None)
        self.update()

    def _pixmap(self, key, img, dpr):
        pm = self._pix.get(key)
        if pm is None:
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            self._pix[key] = pm
            if len(self._pix) > 14:
                for k in list(self._pix)[:6]:
                    self._pix.pop(k, None)
        return pm

    def paintEvent(self, _):
        th = theme(self.st["theme"])
        p = QPainter(self)
        try:
            p.fillRect(self.rect(), QColor(th["desk"]))
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setRenderHint(QPainter.TextAntialiasing, True)
            if not self._layout:
                self._relayout()
            dpr = min(3.0, self.devicePixelRatioF() * float(self.st["render_scale"]))
            dpr = max(1.0, dpr)
            crop_on = bool(self.st["pdf_crop"])
            inv = bool(th["dark"] and self.st["pdf_invert"])
            view = QRectF(self.ox, self.oy, self.width(), self.height())
            visible = []
            for i, r in enumerate(self._layout):
                if r.bottom() < view.top() - 40 or r.top() > view.bottom() + 40:
                    continue
                visible.append(i)
                sx, sy = r.x() - self.ox, r.y() - self.oy
                if self.st["pdf_shadow"]:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(0, 0, 0, 46))
                    p.drawRoundedRect(QRectF(sx + 3, sy + 5, r.width(), r.height()), 3, 3)
                    p.setBrush(QColor(0, 0, 0, 30))
                    p.drawRoundedRect(QRectF(sx + 1, sy + 2, r.width(), r.height()), 3, 3)
                pw = int(min(4200, max(1, r.width() * dpr)))
                ph = int(min(6000, max(1, r.height() * dpr)))
                key = self.engine.request(i, pw, ph, inv, crop_on, front=True)
                img = self.engine.get(key)
                if img is None and not self.engine.path:
                    img = self.engine.sync_render(i, pw, ph, inv)
                if img is not None and not img.isNull():
                    p.drawPixmap(QRectF(sx, sy, r.width(), r.height()),
                                 self._pixmap(key, img, dpr), QRectF(0, 0, img.width(), img.height()))
                else:
                    base = QColor(self.st.get("fg" if inv else "bg", "#f2efe9"))
                    p.fillRect(QRectF(sx, sy, r.width(), r.height()), base)
                    txt = QColor(self.st.get("bg" if inv else "fg", "#9aa2ad"))
                    txt.setAlpha(140)
                    p.setPen(txt)
                    f = p.font(); f.setPointSize(11); p.setFont(f)
                    p.drawText(QRectF(sx, sy, r.width(), r.height()), Qt.AlignCenter, f"стр. {i + 1}")
                p.setPen(QPen(QColor(0, 0, 0, 60), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(sx, sy, r.width(), r.height()))
            for j in (1, 2):
                if visible and visible[-1] + j < self.count:
                    i = visible[-1] + j
                    r = self._layout[i]
                    self.engine.request(i, int(min(4200, r.width() * dpr)),
                                        int(min(6000, r.height() * dpr)), inv, crop_on)
            if self.st["brightness"] < 1.0:
                p.fillRect(self.rect(), QColor(0, 0, 0, int((1 - self.st["brightness"]) * 205)))
        finally:
            p.end()

    def resizeEvent(self, _):
        self._place_bars()
        self._apply_fit()

    # ── ввод ──
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position(), QPointF(self.ox, self.oy), False)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag:
            d = e.position() - self._drag[0]
            if d.manhattanLength() > 5:
                self._drag = (self._drag[0], self._drag[1], True)
                self._scroll_to(self._drag[1].x() - d.x(), self._drag[1].y() - d.y(), smooth=False)

    def mouseReleaseEvent(self, e):
        drag, self._drag = self._drag, None
        self.setCursor(Qt.ArrowCursor)
        if drag and drag[2]:
            return
        if e.button() == Qt.RightButton:
            self.menuRequested.emit(e.globalPosition().toPoint()); return
        if e.button() != Qt.LeftButton:
            return
        if not self.st["tap_zones"]:
            self.next(); return
        x = e.position().x() / max(1, self.width())
        if x < 0.22: self.prev()
        elif x > 0.78: self.next()
        else: self.centerTapped.emit()

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if e.modifiers() & Qt.ControlModifier:
            pt = e.position()
            anchor = ((self.ox + pt.x()) / self.scale, (self.oy + pt.y()) / self.scale)
            self.st["pdf_fit"] = "custom"
            self.st["pdf_zoom"] = max(25, min(600, int(self.scale * 100 * (1.15 if dy > 0 else 1 / 1.15))))
            self._apply_fit(anchor)
            return
        if e.modifiers() & Qt.ShiftModifier:
            self._scroll_to(self._tx - dy * 0.8, self._ty)
        else:
            self._scroll_to(self._tx, self._ty - dy * 0.85)

    def keyPressEvent(self, e):
        k = e.key()
        step = self.height() * 0.88
        if k in (Qt.Key_PageDown, Qt.Key_Space): self.next()
        elif k in (Qt.Key_PageUp, Qt.Key_Backspace): self.prev()
        elif k == Qt.Key_Down: self.scroll_by(120)
        elif k == Qt.Key_Up: self.scroll_by(-120)
        elif k == Qt.Key_Right: self.next()
        elif k == Qt.Key_Left: self.prev()
        elif k == Qt.Key_Home: self.first()
        elif k == Qt.Key_End: self.last()
        elif k in (Qt.Key_Plus, Qt.Key_Equal): self.zoom_step(1)
        elif k == Qt.Key_Minus: self.zoom_step(-1)
        elif k == Qt.Key_0: self.set_fit("width")
        elif k == Qt.Key_9: self.set_fit("page")
        else: super().keyPressEvent(e)