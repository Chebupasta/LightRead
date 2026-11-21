"""Глубокие тесты: тяжёлые форматы, стресс, кэши, крайние случаи.

Запуск: python -m unittest discover -s tests -v
"""
import os
import sys
import time
import zipfile
import unittest
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="lr_deep_"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("APPDATA", str(TMP))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSize, Qt, QRectF
from PySide6.QtGui import QFont, QImage, QPainter, QPdfWriter, QPageSize, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

app = QApplication.instance() or QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)

import common
import formats
import library as libmod
import theming
import ui
import views

ui.StatsDialog.exec = lambda self, *a, **k: None
ui.InfoDialog.exec = lambda self, *a, **k: None

FB2 = TMP / "deep.fb2"
FB2.write_text("""<?xml version="1.0"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info><book-title>Глубокий тест</book-title><author><first-name>Иван</first-name><last-name>Петров</last-name></author></title-info></description>
<body><section><title><p>Глава первая</p></title><p>Привет, глубокий мир! Поисковое слово.</p></section>
<section><title><p>Глава вторая</p></title><p>Продолжение поискового слова.</p></section></body></FictionBook>""", encoding="utf-8")


def make_pdf(path, pages=3):
    w = QPdfWriter(str(path))
    w.setPageSize(QPageSize(QPageSize.A4))
    w.setResolution(120)
    p = QPainter(w)
    p.setFont(QFont("Sans", 12))
    for i in range(pages):
        if i:
            w.newPage()
        p.drawText(80, 90, f"PDF page {i + 1}")
    p.end()


def make_epub(path):
    opf = """<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>EPUB Глубокий</dc:title><dc:creator>Автор</dc:creator><dc:language>ru</dc:language></metadata><manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/><item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>"""
    cont = """<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>"""
    c1 = "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>Первая</title></head><body><h1 id='h1'>Первая глава</h1><p>Привет из EPUB! Поисковое слово.</p></body></html>"
    c2 = "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>Вторая</title></head><body><h1 id='h2'>Вторая глава</h1><p>Продолжение поискового слова.</p></body></html>"
    nav = "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>Навигация</title></head><body><nav epub:type='toc'><ol><li><a href='c1.xhtml#h1'>Первая глава</a></li><li><a href='c2.xhtml#h2'>Вторая глава</a></li></ol></nav></body></html>"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", cont)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/c1.xhtml", c1)
        z.writestr("OEBPS/c2.xhtml", c2)
        z.writestr("OEBPS/nav.xhtml", nav)


def make_docx(path):
    doc = """<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Глава DOCX</w:t></w:r></w:p><w:p><w:r><w:t>Текст документа с поисковым словом.</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Подраздел</w:t></w:r></w:p></w:body></w:document>"""
    rels = "<?xml version='1.0'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'/>"
    core = "<?xml version='1.0'?><cp:coreProperties xmlns:cp='http://schemas.openxmlformats.org/package/2006/metadata/core-properties' xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:title>DOCX Глубокий</dc:title></cp:coreProperties>"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("docProps/core.xml", core)


make_pdf(TMP / "deep.pdf")
make_epub(TMP / "deep.epub")
make_docx(TMP / "deep.docx")


class TestHeavyFormats(unittest.TestCase):
    def test_pdf_parse_render(self):
        src = formats.open_source(str(TMP / "deep.pdf"))
        try:
            self.assertTrue(src.fixed)
            self.assertEqual(src.count, 3)
            ps = src.page_size(0)
            self.assertGreater(ps.width(), 10)
            img = src.render(0, QSize(160, 220))
            self.assertFalse(img.isNull())
        finally:
            src.close()

    def test_epub_parse_toc(self):
        src = formats.open_source(str(TMP / "deep.epub"))
        try:
            self.assertFalse(src.fixed)
            self.assertEqual(src.count, 2)
            self.assertEqual(len(src.toc), 2)
            self.assertIn("Привет", formats.plain(src.chapter(0).html))
        finally:
            src.close()

    def test_docx_headings_toc(self):
        src = formats.open_source(str(TMP / "deep.docx"))
        try:
            self.assertFalse(src.fixed)
            self.assertGreaterEqual(len(src.toc), 2)
            self.assertTrue(any(t[3].startswith("pos:") for t in src.toc))
        finally:
            src.close()

    def test_fixed_reader_controls(self):
        win = ui.Win()
        try:
            bid = win.import_path(str(TMP / "deep.pdf"))
            win.open_book(bid)
            r = win.reader
            self.assertTrue(r.fixed)
            self.assertEqual(r.view.count, 3)
            r.view.goto(2)
            r.view.next(); r.view.prev()
            r.tune_changed("pdf_fit", "page")
            r.tune_changed("pdf_zoom", 150)
            r.tune_changed("pdf_crop", True)
            r.tune_changed("pdf_gap", 24)
            r.tune_changed("brightness", 0.7)
            r.view.grab()
            r.close()
        finally:
            win.close()

    def test_crop_renders_full_page(self):
        win = ui.Win()
        try:
            bid = win.import_path(str(TMP / "deep.pdf"))
            win.open_book(bid)
            r = win.reader
            r.tune_changed("pdf_crop", True)
            r.view.engine.crop[0] = QRectF(0.1, 0.1, 0.8, 0.8)
            calls = []
            original = r.view.engine.request

            def record(i, w, h, inv, crop, front=False):
                calls.append((i, w, h, crop))
                return original(i, w, h, inv, crop, front=front)

            r.view.engine.request = record
            r.view.grab()
            self.assertTrue(calls)
            cropped = [c for c in calls if c[3]]
            self.assertTrue(cropped)
            # при обрезке рендерится полная страница, а не сплющенная область
            self.assertGreater(cropped[0][1], r.view.width() * 0.9)
            r.close()
        finally:
            win.close()

    def test_reflow_toc_anchor(self):
        win = ui.Win()
        try:
            bid = win.import_path(str(TMP / "deep.epub"))
            win.open_book(bid)
            r = win.reader
            self.assertGreater(r.tree.topLevelItemCount(), 0)
            it = r.tree.topLevelItem(1) or r.tree.topLevelItem(0)
            r.toc_click(it, 0)
            r.view.grab()
            r.close()
        finally:
            win.close()


class TestCaches(unittest.TestCase):
    def test_chapter_cache(self):
        src = formats.open_source(str(FB2))
        view = views.ReflowView(src, dict(common.S))
        calls = []
        original = src.chapter

        def counting(i):
            calls.append(i)
            return original(i)

        src.chapter = counting
        try:
            view.load(0); view.load(1); view.load(0)
            self.assertEqual(calls, [0, 1])  # третья загрузка из кэша
        finally:
            src.close()

    def test_search_text_cache(self):
        win = ui.Win()
        try:
            bid = win.import_path(str(FB2))
            win.open_book(bid)
            r = win.reader
            calls = []
            original = r.src.chapter

            def counting(i):
                calls.append(i)
                return original(i)

            r.src.chapter = counting
            r.sq.setText("поисковое")
            r.search()
            first = list(calls)
            calls.clear()
            r.search()
            self.assertTrue(first)
            self.assertEqual(calls, [])  # повторный поиск не парсит главы
            r.close()
        finally:
            win.close()

    def test_delegate_scaled_cache(self):
        win = ui.Win()
        try:
            win.import_path(str(FB2))
            win.reload()
            d = win.deleg
            d._scaled.clear()
            win.grab()
            first = len(d._scaled)
            win.grab()
            self.assertEqual(len(d._scaled), first)  # масштабирование не повторяется
        finally:
            win.close()

    def test_pix_lru_bounded(self):
        win = ui.Win()
        try:
            d = win.deleg
            for i in range(510):
                d._pix[i] = QPixmap()
            d.pix(9999)
            self.assertLessEqual(len(d._pix), 500)
        finally:
            win.close()

    def test_theme_switch_stress(self):
        old = common.S["theme"]
        try:
            t0 = time.time()
            for _ in range(3):
                for name in common.THEMES:
                    theming.apply_theme(name, force=True)
            self.assertLess(time.time() - t0, 10.0)
        finally:
            theming.apply_theme(old, force=True)


class TestStress(unittest.TestCase):
    def test_many_books(self):
        files = []
        for i in range(40):
            p = TMP / f"stress_{i}.fb2"
            p.write_text(FB2.read_text(encoding="utf-8").replace("Глубокий тест", f"Книга {i}"),
                         encoding="utf-8")
            files.append(p)
        win = ui.Win()
        try:
            for p in files:
                win.import_path(str(p))
            t0 = time.time()
            win.reload()
            reload_time = time.time() - t0
            t0 = time.time()
            pm = win.grab()
            paint_time = time.time() - t0
            self.assertFalse(pm.isNull())
            self.assertLess(reload_time, 8.0)
            self.assertLess(paint_time, 8.0)
        finally:
            win.close()

    def test_many_readers_cleanup(self):
        win = ui.Win()
        try:
            for i in range(5):
                p = TMP / f"multi_{i}.fb2"
                p.write_text(FB2.read_text(encoding="utf-8").replace("Глубокий тест", f"Много {i}"),
                             encoding="utf-8")
                win.open_book(win.import_path(str(p)))
            self.assertGreaterEqual(len(win.readers), 5)
            for r in list(win.readers):
                r.close()
            self.assertEqual(len(win.readers), 0)
        finally:
            win.close()


class TestEdgeCases(unittest.TestCase):
    def test_corrupt_file_no_crash(self):
        bad = TMP / "bad.fb2"
        bad.write_text("<FictionBook><broken>", encoding="utf-8")
        win = ui.Win()
        try:
            result = win.import_path(str(bad))
            win.reload()
            self.assertTrue(result is None or isinstance(result, int))
        finally:
            win.close()

    def test_duplicate_import(self):
        win = ui.Win()
        try:
            a = win.import_path(str(FB2))
            b = win.import_path(str(FB2))
            self.assertEqual(a, b)
            self.assertEqual(len([r for r in win.lib.books() if r["path"] == common.norm(FB2)]), 1)
        finally:
            win.close()

    def test_long_unicode_title(self):
        title = '<Тест & "кавычки"> ' + "Очень длинное название " * 8 + "📚"
        win = ui.Win()
        try:
            bid = win.import_path(str(FB2))
            win.lib.set_meta(bid, title=title)
            win.reload()
            win.grab()
            self.assertEqual(win.lib.book(bid)["title"], title)
            dlg = ui.InfoDialog(win.lib, bid, win)
            self.assertEqual(dlg.f_title.text(), title)
            dlg.save()
        finally:
            win.close()

    def test_settings_roundtrip(self):
        old = common.S["font_size"]
        try:
            common.S["font_size"] = 23
            common.S.save()
            s = common.Settings()
            self.assertEqual(s["font_size"], 23)
        finally:
            common.S["font_size"] = old
            common.S.save()

    def test_backup_zip(self):
        win = ui.Win()
        out = TMP / "backup_test.zip"
        try:
            ui.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out), ""))
            win.backup()
            self.assertTrue(out.exists())
            with zipfile.ZipFile(out) as z:
                names = z.namelist()
            self.assertIn("library.db", names)
        finally:
            win.close()


class TestSearchSemantics(unittest.TestCase):
    def test_offset_matches_reader_text(self):
        html = TMP / "tables.html"
        html.write_text("<html><head><title>Сложный HTML</title></head><body><h1>Глава</h1>"
                        "<p>START <img src='x.png'/> after IMG</p>"
                        "<ul><li>one</li><li>two</li></ul>"
                        "<table><tr><td>A</td><td>B</td></tr></table>"
                        "<p>ENDMARK</p></body></html>", encoding="utf-8")
        win = ui.Win()
        try:
            bid = win.import_path(str(html))
            win.open_book(bid)
            r = win.reader
            r.sq.setText("ENDMARK")
            r.search()
            self.assertGreater(r.sres.count(), 0)
            ch, pos = r.sres.item(0).data(Qt.UserRole)
            self.assertEqual(ch, 0)
            self.assertEqual(r.view._text[pos:pos + len("ENDMARK")].lower(), "endmark")
            # переход по результату должен подсвечивать найденный фрагмент
            r.search_step(1)
            s, e = sorted(r.view.sel)
            self.assertEqual(r.view._text[s:e].lower(), "endmark")
            r.close()
        finally:
            win.close()

    def test_search_limit_and_wrap(self):
        txt = TMP / "manyhits.txt"
        txt.write_text("Заголовок\n" + ("aa " * 600), encoding="utf-8")
        win = ui.Win()
        try:
            bid = win.import_path(str(txt))
            win.open_book(bid)
            r = win.reader
            r.sq.setText("aa")
            r.search()
            self.assertLessEqual(r.sres.count(), 400)
            r.search_step(1); r.search_step(1); r.search_step(-1)
            self.assertGreaterEqual(r._hit_i, 0)
            r.close()
        finally:
            win.close()


class TestRegressions(unittest.TestCase):
    def test_duplicate_tag_and_coll_ids(self):
        lib = libmod.Library(path=str(TMP / "dupes.db"))
        try:
            t1 = lib.new_tag("Метка")
            lib.new_tag("Другая")
            t2 = lib.new_tag("Метка")
            self.assertEqual(t1, t2)
            c1 = lib.new_coll("Коллекция")
            lib.new_coll("Другая коллекция")
            c2 = lib.new_coll("Коллекция")
            self.assertEqual(c1, c2)
        finally:
            lib.c.close()

    def test_reader_close_updates_list(self):
        win = ui.Win()
        try:
            bid = win.import_path(str(FB2))
            win.open_book(bid)
            r = win.reader
            r.close()
            self.assertEqual(len(win.readers), 0)
            self.assertIsNone(win.reader)
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
