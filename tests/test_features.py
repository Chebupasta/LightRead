"""Автотесты новых возможностей: главный экран, вкладки, интеграции и UX."""
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="lr_features_"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = str(TMP)
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QTabBar, QStyleOptionViewItem, QLabel

app = QApplication.instance() or QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)

import common
import formats
import library as libmod
import services
import theming
import ui
from reader import Reader


FB2_TEXT = '''<?xml version="1.0"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info><book-title>Тестовая книга</book-title>
<author><first-name>Иван</first-name><last-name>Петров</last-name></author>
</title-info></description><body><section><title><p>Глава</p></title>
<p>Привет мир, это тестовая книга для новых возможностей.</p></section></body></FictionBook>'''


@contextmanager
def settings(**kwargs):
    old = {k: common.S[k] if k in common.S else common.DEFAULTS[k] for k in kwargs}
    common.S.update(kwargs)
    try:
        yield
    finally:
        common.S.update(old)
        common.S.save()


def make_book(path, title="Тестовая книга"):
    path.write_text(FB2_TEXT.replace("Тестовая книга", title), encoding="utf-8")
    return path


class TestMarkdown(unittest.TestCase):
    def test_extended_syntax(self):
        html = formats.md_to_html("""# Заголовок

| A | B |
|---|---|
| 1 | 2 |

- [ ] задача
- [x] сделано

---

Текст[^1]

[^1]: сноска
""")
        self.assertIn("<table>", html)
        self.assertIn("<b>A</b>", html)
        self.assertIn("<hr/>", html)
        self.assertIn("<sup>1</sup>", html)
        self.assertTrue("☐" in html and "☑" in html)

    def test_soft_hyphenation(self):
        with settings(hyphenate=True):
            html = formats.text_to_html("Programming extraordinarily complicated sentence")
            self.assertIn("\u00ad", html)
        with settings(hyphenate=False):
            html = formats.text_to_html("Programming extraordinarily complicated sentence")
            self.assertNotIn("\u00ad", html)


class TestOfficeFormats(unittest.TestCase):
    def test_docx_keeps_formatting(self):
        p = TMP / "format.docx"
        document = '''<?xml version="1.0"?><w:document
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:jc w:val="center"/></w:pPr>
 <w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t>Заголовок</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr>
 <w:r><w:rPr><w:i/></w:rPr><w:t>Курсивный пункт</w:t></w:r></w:p>
</w:body></w:document>'''
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", document)
            z.writestr("word/_rels/document.xml.rels",
                       "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'/>")
            z.writestr("word/styles.xml",
                       "<w:styles xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>")
        src = formats.open_source(str(p))
        html = src.chapter(0).html
        self.assertIn("<h1", html)
        self.assertIn("<b>", html)
        self.assertIn("<i>", html)
        self.assertIn("text-align:center", html)
        self.assertIn("<ul>", html)
        src.close()

    def test_docx_cover_is_not_first_image(self):
        p = TMP / "cover.docx"
        image = b"\x89PNG\r\n\x1a\nFAKE"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", '''<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>Титульная страница</w:t></w:r></w:p></w:body></w:document>''')
            z.writestr("word/media/image1.png", image)
        src = formats.open_source(str(p))
        self.assertNotEqual(src.meta.cover, image)
        src.close()

    def test_pptx_parse(self):
        p = TMP / "deck.pptx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("docProps/core.xml", '''<?xml version="1.0"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Презентация</dc:title></cp:coreProperties>''')
            z.writestr("ppt/presentation.xml", '''<?xml version="1.0"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<p:sldIdLst><p:sldId r:id="rId1"/></p:sldIdLst></p:presentation>''')
            z.writestr("ppt/_rels/presentation.xml.rels", '''<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Target="slides/slide1.xml"/></Relationships>''')
            z.writestr("ppt/slides/slide1.xml", '''<?xml version="1.0"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>
<p:sp><p:txBody><a:p><a:r><a:t>Слайд один</a:t></a:r></a:p>
<a:p><a:r><a:t>Пункт презентации</a:t></a:r></a:p></p:txBody></p:sp>
</p:spTree></p:cSld></p:sld>''')
        src = formats.open_source(str(p))
        self.assertEqual(src.meta.title, "Презентация")
        self.assertEqual(src.count, 1)
        html = src.chapter(0).html
        self.assertIn("Слайд один", html)
        self.assertIn("Пункт презентации", html)
        src.close()
        self.assertEqual(formats.read_meta(str(p))[1], "pptx")

    def test_odp_parse(self):
        p = TMP / "deck.odp"
        content = '''<?xml version="1.0"?><office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
<office:body><office:presentation>
<draw:page draw:name="Титул"><text:p>Заголовок ODP</text:p><text:p>Подзаголовок</text:p></draw:page>
<draw:page draw:name="Второй"><text:p>Второй слайд</text:p></draw:page>
</office:presentation></office:body></office:document-content>'''
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("content.xml", content)
        src = formats.open_source(str(p))
        self.assertEqual(src.count, 2)
        self.assertIn("Заголовок ODP", src.chapter(0).html)
        self.assertIn("Второй слайд", src.chapter(1).html)
        src.close()
        self.assertEqual(formats.read_meta(str(p))[1], "odp")

    def test_legacy_doc_text_fallback(self):
        p = TMP / "legacy.doc"
        p.write_bytes(b"\xd0\xcf\x11\xe0" + "Легаси документ Ворд".encode("utf-16le"))
        src = formats.open_source(str(p))
        self.assertGreaterEqual(src.count, 1)
        self.assertIn("Легаси", src.chapter(0).html)
        src.close()

    def test_legacy_ppt_text_fallback(self):
        p = TMP / "legacy.ppt"
        p.write_bytes(b"\xd0\xcf\x11\xe0" + "Легаси презентация Слайд".encode("utf-16le"))
        src = formats.open_source(str(p))
        self.assertGreaterEqual(src.count, 1)
        self.assertIn("Легаси", src.chapter(0).html)
        src.close()

    def test_presentation_extensions_registered(self):
        for ext in (".pptx", ".ppt", ".pps", ".ppsx", ".potx", ".odp", ".otp"):
            self.assertIn(ext, formats.ALL_EXTS)


def _contrast(a, b):
    def lum(value):
        value = value.lstrip("#")
        rgb = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestFileProperties(unittest.TestCase):
    def test_properties_show_path_size_and_dates(self):
        db = TMP / f"props_{self.id()}.db"
        lib = libmod.Library(path=str(db))
        try:
            p = make_book(TMP / f"props_{self.id()}.fb2", "Книга свойств")
            bid = lib.upsert(dict(path=str(p), fmt="fb2", title="Книга свойств", author="A",
                                  series="", seq=0, lang="ru", annotation="", genres="",
                                  size=p.stat().st_size, mtime=p.stat().st_mtime))
            dlg = ui.FilePropertiesDialog(lib, bid)
            texts = [w.text() for w in dlg.findChildren(QLabel)]
            joined = "\n".join(texts)
            self.assertIn(common.norm(str(p)).lower(), joined.lower())
            self.assertIn(p.name.lower(), joined.lower())
            self.assertIn("FB2", joined)
            self.assertIn("Размер на диске", joined)
            self.assertIn("Изменён", joined)
            tabs = dlg.findChild(ui.QTabWidget)
            self.assertIsNotNone(tabs)
            self.assertIn("Метаданные", [tabs.tabText(i) for i in range(tabs.count())])
        finally:
            lib.c.close()


class TestPalette(unittest.TestCase):
    def test_surface_roles_are_distinct_and_readable(self):
        for name in common.THEMES:
            c = theming.chrome(common.theme(name))
            surfaces = [c[k] for k in ("bg.canvas", "bg.overlay", "bg.field", "bg.panel",
                                       "bg.subtle", "bg.raised", "bg.hover", "bg.selected", "bg.active")]
            self.assertGreaterEqual(len(set(surfaces)), 8, name)
            self.assertNotEqual(c["border.subtle"], c["bg.selected"], name)
            self.assertNotEqual(c["border.strong"], c["bg.active"], name)
            self.assertNotEqual(c["accent.subtle"], c["bg.hover"], name)
            self.assertGreaterEqual(_contrast(c["text.primary"], c["bg.canvas"]), 4.5, name)
            self.assertGreaterEqual(_contrast(c["text.secondary"], c["bg.panel"]), 4.0, name)
            self.assertGreaterEqual(_contrast(c["text.tertiary"], c["bg.raised"]), 3.0, name)


class TestLocalReliability(unittest.TestCase):
    def test_corrupt_db_is_recovered(self):
        db = TMP / "corrupt.db"
        db.write_bytes(b"this is not a sqlite database")
        lib = libmod.Library(path=str(db))
        try:
            self.assertFalse(lib.integrity_ok)
            self.assertTrue(Path(lib.integrity_backup).exists())
            self.assertEqual(lib.q("SELECT * FROM books"), [])
        finally:
            lib.c.close()

    def test_fts_search_finds_note_text(self):
        db = TMP / f"fts_{self.id()}.db"
        lib = libmod.Library(path=str(db))
        try:
            p = make_book(TMP / f"fts_{self.id()}.fb2")
            bid = lib.upsert(dict(path=str(p), fmt="fb2", title="T", author="", series="", seq=0,
                                  lang="", annotation="", genres="", size=1, mtime=1))
            lib.note_add(bid, 0, 0, 3, "#fff", "цитата", "УНИКАЛЬНОЕ_СЛОВО_ФТС")
            self.assertTrue(lib.fts_ok)
            rows = lib.books(search="УНИКАЛЬНОЕ_СЛОВО_ФТС")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], bid)
        finally:
            lib.c.close()

    def test_network_actions_hidden_by_default(self):
        win = ui.Win()
        try:
            texts = [a.text() for a in win.menuBar().actions()]
            self.assertFalse(any("OPDS" in t for t in texts))
        finally:
            win.close()


class TestHashDedupe(unittest.TestCase):
    def test_scanner_skips_identical_files(self):
        d = TMP / "dupes"
        d.mkdir(exist_ok=True)
        text = make_book(d / "one.fb2").read_text(encoding="utf-8")
        (d / "two.fb2").write_text(text, encoding="utf-8")
        scanner = ui.Scanner([str(d)], {}, {})
        found = []
        scanner.found.connect(lambda data: found.append(data))
        scanner.run()
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["fhash"])


class TestSmartCollections(unittest.TestCase):
    def setUp(self):
        self.db = TMP / f"smart_{self.id()}.db"
        self.lib = libmod.Library(path=str(self.db))
        p = make_book(TMP / f"smart_{self.id()}.fb2")
        self.bid = self.lib.upsert(dict(path=str(p), fmt="fb2", title="T", author="", series="",
                                        seq=0, lang="", annotation="", genres="", size=1, mtime=1))

    def tearDown(self):
        self.lib.c.close()

    def test_rule_filters_by_status(self):
        rule = dict(name="Новые", status="new", fmt="", tag=0, favorite=False,
                    days=0, min_progress=0.0, max_progress=1.0)
        with settings(smart=[rule]):
            self.lib.set_field(self.bid, status="new")
            self.assertEqual(len(self.lib.books(dict(kind="smart", value="Новые"))), 1)
            self.lib.set_field(self.bid, status="read")
            self.assertEqual(len(self.lib.books(dict(kind="smart", value="Новые"))), 0)


class TestSync(unittest.TestCase):
    def test_export_apply_roundtrip(self):
        p = make_book(TMP / "sync.fb2")
        a = libmod.Library(path=str(TMP / "sync_a.db"))
        bid = a.upsert(dict(path=str(p), fmt="fb2", title="T", author="", series="", seq=0,
                            lang="", annotation="", genres="", size=1, mtime=1))
        a.set_progress(bid, 1, 22, 0.5, 10)
        a.mark_add(bid, 0, 5, "M", "text")
        a.note_add(bid, 0, 2, 12, "#fff", "quote", "note", anchor="quote")
        snapshot = services.Sync.export(a)
        a.c.close()

        b = libmod.Library(path=str(TMP / "sync_b.db"))
        b.upsert(dict(path=str(p), fmt="fb2", title="T", author="", series="", seq=0,
                      lang="", annotation="", genres="", size=1, mtime=1))
        services.Sync.apply(b, snapshot)
        row = b.book(b.by_path(str(p))["id"])
        self.assertAlmostEqual(row["progress"], 0.5)
        self.assertEqual(row["status"], "reading")
        self.assertEqual(len(b.q("SELECT * FROM marks")), 1)
        self.assertEqual(len(b.q("SELECT * FROM notes")), 1)
        b.c.close()


class TestIntegrations(unittest.TestCase):
    def test_opds_atom_parse(self):
        feed = TMP / "feed.atom"
        feed.write_text('''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<title>Test</title><entry><title>Book</title><id>b1</id>
<author><name>Author</name></author>
<link rel="http://opds-spec.org/acquisition" href="file:///tmp/book.epub"/></entry></feed>''',
                        encoding="utf-8")
        entries, _next = services.Opds(feed.as_uri()).feed()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Book")
        self.assertEqual(entries[0]["author"], "Author")
        self.assertIn("http://opds-spec.org/acquisition", entries[0]["links"])

    def test_opds_relative_links(self):
        feed = TMP / "relative.atom"
        feed.write_text('''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<title>Test</title><link rel="next" href="page2.xml"/>
<entry><title>Book</title><id>b1</id>
<link rel="http://opds-spec.org/acquisition" href="books/book.epub"/></entry></feed>''',
                        encoding="utf-8")
        entries, nxt = services.Opds(feed.as_uri()).feed()
        self.assertTrue(entries[0]["links"]["http://opds-spec.org/acquisition"].endswith("books/book.epub"))
        self.assertTrue(nxt.endswith("page2.xml"))

    def test_update_check_parse(self):
        release = TMP / "release.json"
        release.write_text('{"tag_name":"v2.0","html_url":"https://example.com/r","body":"notes"}',
                           encoding="utf-8")
        info = services.Update(release.as_uri()).check()
        self.assertEqual(info["version"], "v2.0")
        self.assertEqual(info["url"], "https://example.com/r")
        self.assertEqual(info["notes"], "notes")


class TestHomeAndTabs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = ui.Win()
        cls.win.show()
        cls.p = make_book(TMP / "home.fb2")
        cls.bid = cls.win.import_path(str(cls.p))
        cls.win.lib.set_progress(cls.bid, 0, 10, 0.4, 10)
        cls.win.reload()

    @classmethod
    def tearDownClass(cls):
        for r in list(cls.win.readers):
            r.close()
        cls.win.close()

    def test_home_tabs(self):
        texts = [self.win.book_tabs.tabText(i) for i in range(self.win.book_tabs.count())]
        self.assertTrue(any("Главная" in t for t in texts))
        self.assertTrue(any("Библиотека" in t for t in texts))
        self.assertIsNone(self.win.book_tabs.tabBar().tabButton(ui.HOME_TAB, QTabBar.RightSide))
        self.assertIsNone(self.win.book_tabs.tabBar().tabButton(ui.LIB_TAB, QTabBar.RightSide))

    def test_home_continue_and_recent(self):
        self.win.lib.set_progress(self.bid, 0, 10, 0.4, 10)
        self.win.reload()
        self.assertFalse(self.win.cont.isHidden())
        self.assertEqual(self.win._continue_id, self.bid)
        self.assertGreaterEqual(self.win.home.recent_layout.count(), 1)

    def test_hover_actions_rendered(self):
        self.win.set_view("grid")
        pm = QPixmap(300, 400)
        p = QPainter(pm)
        opt = QStyleOptionViewItem()
        opt.rect = pm.rect()
        self.win.deleg.hover = self.bid
        self.win.deleg.paint(p, opt, self.win.model.index(0, 0))
        p.end()
        self.assertTrue({"read", "fav", "info"}.issubset(self.win.deleg.action_rects))
        self.win.deleg.hover = None

    def test_fullscreen_restores_on_reader_close(self):
        self.win.open_book(self.bid)
        reader = self.win.reader
        reader.fullscreen()
        self.assertTrue(self.win.isFullScreen())
        reader.close()
        self.assertFalse(self.win.isFullScreen())

    def test_nav_and_toast(self):
        self.assertIsInstance(self.win.tree.itemDelegate(), ui.NavDelegate)
        self.win.notify("тест")
        self.assertTrue(self.win.toast.isVisible())
        self.assertEqual(self.win.toast.label.text(), "тест")

    def test_group_and_reopen_tab(self):
        self.win.open_book(self.bid)
        reader = self.win.reader
        self.win.assign_group(reader, "ГруппаA")
        index = self.win.book_tabs.indexOf(reader)
        self.assertIn("ГруппаA", self.win.book_tabs.tabText(index))
        self.assertFalse(self.win.book_tabs.tabIcon(index).isNull())
        reader.close()
        self.win.reopen_closed_tab()
        self.assertIsNotNone(self.win.reader)
        self.win.reader.close()


class TestNoteEditor(unittest.TestCase):
    def test_draft_autosaved_and_cleared(self):
        db = TMP / f"draft_{self.id()}.db"
        lib = libmod.Library(path=str(db))
        p = make_book(TMP / f"draft_{self.id()}.fb2")
        bid = lib.upsert(dict(path=str(p), fmt="fb2", title="T", author="", series="", seq=0,
                              lang="", annotation="", genres="", size=1, mtime=1))
        with settings(note_drafts={}):
            reader = Reader(lib, lib.book(bid))
            try:
                reader.note_edit.setPlainText("черновик")
                reader.save_draft()
                self.assertEqual(common.S["note_drafts"][str(bid)], "черновик")
                reader.note_edit.setPlainText("готово")
                reader.save_note_text()
                self.assertNotIn(str(bid), common.S["note_drafts"])
            finally:
                reader.close()
                lib.c.close()

    def test_editor_saves_note_and_plain_anchor(self):
        db = TMP / f"note_{self.id()}.db"
        lib = libmod.Library(path=str(db))
        p = make_book(TMP / f"note_{self.id()}.fb2")
        bid = lib.upsert(dict(path=str(p), fmt="fb2", title="T", author="", series="", seq=0,
                              lang="", annotation="", genres="", size=1, mtime=1))
        reader = Reader(lib, lib.book(bid))
        try:
            reader.note_edit.setPlainText("Текст из редактора")
            reader.save_note_text()
            notes = lib.notes(bid)
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["note"], "Текст из редактора")
            self.assertNotIn("\u00ad", notes[0]["anchor"] or "")
        finally:
            reader.close()
            lib.c.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
