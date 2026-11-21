"""Автотесты LightRead (offscreen, без UI-диалогов).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = tempfile.mkdtemp(prefix="lr_tests_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = TMP
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)

import common
import formats
import library as libmod
import reader as reader_mod
import theming
import ui
import views

# модальные диалоги в тестах не открываем
ui.StatsDialog.exec = lambda self, *a, **k: None
ui.InfoDialog.exec = lambda self, *a, **k: None

WORK = Path(TMP)
FB2 = WORK / "book.fb2"
TXT = WORK / "book.txt"
HTML = WORK / "book.html"

FB2.write_text("""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info><book-title>Тест FB2</book-title>
<author><first-name>Иван</first-name><last-name>Петров</last-name></author>
<annotation>Аннотация</annotation></title-info></description>
<body><section><title><p>Глава первая</p></title><p>Привет, мир! Это тестовая книга.</p>
<p>Вторая строка текста.</p></section>
<section><title><p>Глава вторая</p></title><p>Продолжение истории.</p></section></body>
</FictionBook>""", encoding="utf-8")
TXT.write_text("Начало книги.\n\nГлава 1\n" + ("Текст первой главы. " * 30) +
               "\n\nГлава 2\n" + ("Текст второй главы. " * 30), encoding="utf-8")
HTML.write_text("<html><head><title>HTML Книга</title></head><body><h1>Заголовок</h1>"
                "<p>Текст <b>жирный</b> и <i>курсив</i>.</p><p>Второй абзац.</p></body></html>",
                encoding="utf-8")


def contrast(a, b):
    def lum(h):
        h = h.lstrip("#")
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    l1, l2 = sorted((lum(a), lum(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


class TestFormats(unittest.TestCase):
    def test_fb2(self):
        meta, fmt = formats.read_meta(str(FB2))
        self.assertEqual(fmt, "fb2")
        self.assertIn("Тест FB2", meta.title)
        src = formats.open_source(str(FB2))
        try:
            self.assertGreaterEqual(src.count, 2)
            text = formats.plain(src.chapter(0).html)
            self.assertIn("Привет", text)
        finally:
            src.close()

    def test_txt(self):
        src = formats.open_source(str(TXT))
        try:
            self.assertGreaterEqual(src.count, 2)
        finally:
            src.close()

    def test_html(self):
        src = formats.open_source(str(HTML))
        try:
            self.assertGreaterEqual(src.count, 1)
            self.assertIn("Текст", formats.plain(src.chapter(0).html))
        finally:
            src.close()


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.db = WORK / f"lib_{self.id()}.db"
        self.lib = libmod.Library(path=str(self.db))

    def tearDown(self):
        self.lib.c.close()

    def book(self, path=FB2):
        return self.lib.upsert(dict(path=str(path), fmt="fb2", title="Из файла", author="Автор",
                                    series="", seq=0, lang="ru", annotation="", genres="",
                                    size=path.stat().st_size, mtime=path.stat().st_mtime))

    def test_progress_and_status(self):
        bid = self.book()
        self.lib.set_progress(bid, 1, 22, 0.5, 10)
        b = self.lib.book(bid)
        self.assertEqual(b["status"], "reading")
        self.assertEqual(b["chapter"], 1)
        self.lib.set_progress(bid, 0, 0, 1.0, 10)
        self.assertEqual(self.lib.book(bid)["status"], "read")

    def test_metadata_manual_protection(self):
        bid = self.book()
        self.lib.set_meta(bid, title="Ручное название", seq=2.5)
        self.book()  # повторное сканирование не должно перезаписать ручные поля
        b = self.lib.book(bid)
        self.assertEqual(b["title"], "Ручное название")
        self.assertEqual(b["manual_meta"], 1)
        self.assertAlmostEqual(b["seq"], 2.5)

    def test_tags(self):
        bid = self.book()
        tid = self.lib.new_tag("Важное")
        self.lib.tag_book(tid, bid, True)
        self.assertEqual([r["id"] for r in self.lib.books(dict(kind="tag", value=tid))], [bid])
        self.lib.tag_book(tid, bid, False)
        self.assertEqual(self.lib.books(dict(kind="tag", value=tid)), [])

    def test_marks_notes_stats(self):
        bid = self.book()
        mid = self.lib.mark_add(bid, 0, 5, "Закладка", "текст")
        self.lib.mark_upd(mid, title="Новое имя")
        self.assertEqual(self.lib.marks(bid)[0]["title"], "Новое имя")
        nid = self.lib.note_add(bid, 0, 2, 12, "#ffc94a", "цитата", "заметка")
        self.lib.note_upd(nid, note="изменено")
        self.assertEqual(self.lib.notes(bid)[0]["note"], "изменено")
        self.lib.stats_add(bid, 120, 3)
        self.assertEqual(self.lib.stats()[0]["s"], 120)
        self.assertEqual(self.lib.book(bid)["seconds"], 120)


class TestThemes(unittest.TestCase):
    def test_contrast(self):
        for name, th in common.THEMES.items():
            self.assertGreaterEqual(contrast(th["fg"], th["bg"]), 4.5, f"тема {name}: текст")

    def test_aliases_and_chrome(self):
        for old in ("День", "Сепия", "Лён", "Зелень"):
            self.assertEqual(common.norm_theme(old), "Светлая")
        for old in ("Ночь", "AMOLED", "Сумерки", "Графит", "Контраст", "Консоль"):
            self.assertEqual(common.norm_theme(old), "Тёмная")
        self.assertEqual(common.norm_theme("нет такой"), "Светлая")
        self.assertEqual(common.theme("Светлая")["bg"], "#ffffff")
        self.assertEqual(common.theme("Тёмная")["bg"], "#000000")
        for name in common.THEMES:
            c = theming.chrome(common.theme(name))
            for key in ("win", "panel", "field", "border", "text", "dim", "accent", "track", "chip"):
                self.assertTrue(c.get(key))

    def test_two_themes_only(self):
        self.assertEqual(list(common.THEMES), ["Светлая", "Тёмная"])

    def test_rounded_widgets(self):
        """Все видимые элементы должны иметь скруглённые углы."""
        css = theming.TPL
        selectors = (
            "QFrame {", "QToolTip", "QMenu {", "QMenu::item", "QMenuBar::item",
            "QToolButton {", "QStatusBar QLabel", "QStatusBar QSpinBox",
            "QDockWidget {", "QDockWidget::title", "QTabWidget::pane", "QTabBar::tab",
            "QLineEdit,", "QComboBox QAbstractItemView", "QSpinBox::up-button",
            "QPushButton {", "QCheckBox::indicator", "QRadioButton::indicator",
            "QTreeWidget::item", "QScrollBar::handle:vertical", "QScrollBar::handle:horizontal",
            "QSlider::groove:horizontal", "QSlider::handle:horizontal",
            "QProgressBar {", "QProgressBar::chunk", "QWidget#TuneBar QComboBox",
            "QWidget#TuneBar QPushButton", "QLabel#Chip", "QFrame#ContinueBar",
            "QPushButton#ContinueBtn", "QGroupBox {",
        )
        for sel in selectors:
            i = css.find(sel)
            self.assertGreaterEqual(i, 0, f"нет правила {sel}")
            block = css[i:css.find("}", i)]
            self.assertIn("border-radius", block, f"нет скругления у {sel}")

    def test_font_cache(self):
        views.pick_font.cache_clear()
        self.assertEqual(views.pick_font(""), views.pick_font(""))
        self.assertGreaterEqual(views.pick_font.cache_info().hits, 1)


class TestUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = ui.Win()
        cls.bids = [cls.win.import_path(str(p)) for p in (FB2, TXT, HTML)]
        cls.win.reload()

    @classmethod
    def tearDownClass(cls):
        for r in list(cls.win.readers):
            r.close()
        cls.win.close()

    def test_library_view(self):
        self.assertGreaterEqual(self.win.model.rowCount(), 3)
        self.win.set_view("list")
        self.assertFalse(self.win.deleg.grid)
        self.win.set_view("grid")
        self.assertTrue(self.win.deleg.grid)

    def test_search_filter(self):
        # не зависим от порядка тестов: задаём уникальное название сами
        base = self.win.model.rowCount()
        self.win.lib.set_meta(self.bids[0], title="Поисковый УНИКУМ")
        self.win.q.setText("УНИКУМ")
        self.win.reload()
        self.assertGreaterEqual(self.win.model.rowCount(), 1)
        self.win.q.setText("несуществующая книга")
        self.win.reload()
        self.assertEqual(self.win.model.rowCount(), 0)
        self.win.q.setText("")
        self.win.reload()
        self.assertEqual(self.win.model.rowCount(), base)

    def test_continue_reading(self):
        self.win.lib.set_progress(self.bids[0], 0, 0, 0.4, 10)
        self.win.reload()
        self.assertFalse(self.win.cont.isHidden())
        self.assertEqual(self.win._continue_id, self.bids[0])
        self.win.continue_reading()
        self.assertIsNotNone(self.win.reader)
        self.win.reader.close()

    def test_info_dialog_and_tags(self):
        bid = self.bids[0]
        tid = self.win.lib.new_tag("Тестовая метка")
        self.win.lib.tag_book(tid, bid, True)
        self.win.reload()
        names = [self.win.tree.topLevelItem(i).text(0)
                 for i in range(self.win.tree.topLevelItemCount())]
        self.assertTrue(any(n.startswith("Метки") for n in names))
        dlg = ui.InfoDialog(self.win.lib, bid, self.win)
        dlg.f_title.setText("Название из теста")
        dlg.save()
        self.assertEqual(self.win.lib.book(bid)["title"], "Название из теста")
        self.win.reload()

    def test_stats_dialog(self):
        dlg = ui.StatsDialog(self.win.lib, self.win)
        self.assertIsNotNone(dlg.grab())


class TestReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = ui.Win()
        cls.bid = cls.win.import_path(str(FB2))
        cls.win.open_book(cls.bid)
        cls.r = cls.win.reader

    @classmethod
    def tearDownClass(cls):
        for r in list(cls.win.readers):
            r.close()
        cls.win.close()

    def test_open_and_navigate(self):
        self.assertIsNotNone(self.r)
        self.assertGreaterEqual(self.r.src.count, 2)
        self.r.chapter_step(1)
        self.r.chapter_step(-1)
        self.r.slider_move(500)
        self.r.page_jump(1)
        self.assertGreaterEqual(self.r.view.pages, 1)

    def test_search(self):
        self.r.sq.setText("Привет")
        self.r.search()
        self.assertGreater(self.r.sres.count(), 0)
        self.r.search_step(1)
        self.r.search_step(-1)

    def test_bookmarks_and_notes(self):
        before = len(self.r.lib.notes(self.bid))
        self.r.view.sel = (2, 22)
        self.r.make_note("#ffc94a", "тест")
        self.assertEqual(len(self.r.lib.notes(self.bid)), before + 1)
        self.r.add_mark()
        self.assertGreater(self.r.marks.count(), 0)

    def test_theme_cycle_global(self):
        old = common.S["theme"]
        try:
            self.r.cycle_theme()
            self.assertEqual(common.S["theme"], self.r.st["theme"])
        finally:
            common.S["theme"] = old
            common.S.save()
            theming.apply_theme(old, force=True)

    def test_tune_brightness(self):
        self.r.tune_changed("brightness", 0.6)
        self.assertAlmostEqual(self.r.st["brightness"], 0.6)
        self.assertAlmostEqual(self.r.view.st["brightness"], 0.6)

    def test_multidocument(self):
        other = self.win.import_path(str(TXT))
        self.win.open_book(other)
        self.assertGreaterEqual(len(self.win.readers), 2)
        for r in list(self.win.readers):
            if r is not self.r:
                r.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
