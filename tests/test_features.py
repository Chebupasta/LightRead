"""Автотесты новых возможностей: главный экран, вкладки, интеграции и UX."""
import os
import sys
import tempfile
import time
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
import formats_extra
import library as libmod
import services
import theming
import ui
import views
import reader as reader_mod
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
<p:sp><p:txBody><a:p><a:pPr algn="ctr"/><a:r><a:rPr b="1" sz="3600"><a:solidFill><a:srgbClr val="C00000"/></a:solidFill></a:rPr><a:t>Слайд один</a:t></a:r></a:p>
<a:p><a:r><a:rPr i="1"/><a:t>Пункт презентации</a:t></a:r></a:p></p:txBody></p:sp>
</p:spTree></p:cSld></p:sld>''')
        src = formats.open_source(str(p))
        self.assertEqual(src.meta.title, "Презентация")
        self.assertEqual(src.count, 1)
        html = src.chapter(0).html
        self.assertIn("Слайд один", html)
        self.assertIn("Пункт презентации", html)
        self.assertIn("<b>", html)
        self.assertIn("<i>", html)
        self.assertIn("color:#C00000", html)
        self.assertIn("text-align:center", html)
        src.close()
        self.assertEqual(formats.read_meta(str(p))[1], "pptx")

    def test_odp_parse(self):
        p = TMP / "deck.odp"
        content = '''<?xml version="1.0"?><office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
<office:automatic-styles><style:style style:name="T1">
<style:text-properties fo:font-weight="bold" fo:color="#C00000"/>
</style:style></office:automatic-styles>
<office:body><office:presentation>
<draw:page draw:name="Титул"><text:p text:style-name="T1">Заголовок ODP</text:p><text:p>Подзаголовок</text:p></draw:page>
<draw:page draw:name="Второй"><text:p>Второй слайд</text:p></draw:page>
</office:presentation></office:body></office:document-content>'''
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("content.xml", content)
        src = formats.open_source(str(p))
        self.assertEqual(src.count, 2)
        self.assertIn("Заголовок ODP", src.chapter(0).html)
        self.assertIn("<b>", src.chapter(0).html)
        self.assertIn("color:#C00000", src.chapter(0).html)
        self.assertIn("Второй слайд", src.chapter(1).html)
        src.close()
        self.assertEqual(formats.read_meta(str(p))[1], "odp")

    def test_odt_keeps_inline_and_paragraph_formatting(self):
        p = TMP / "format.odt"
        content = '''<?xml version="1.0"?><office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
<office:automatic-styles>
 <style:style style:name="P1">
  <style:paragraph-properties fo:text-align="center"/>
  <style:text-properties fo:font-weight="bold" fo:font-style="italic"
   fo:color="#C00000" fo:font-size="16pt" style:text-underline-style="solid"/>
 </style:style>
 <style:style style:name="P2">
  <style:text-properties fo:font-weight="normal" fo:font-style="normal"/>
 </style:style>
</office:automatic-styles>
<office:body><office:text>
 <text:p text:style-name="P1">Жирный курсив</text:p>
 <text:p text:style-name="P2">Обычный текст</text:p>
</office:text></office:body></office:document-content>'''
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("content.xml", content)
        src = formats.open_source(str(p))
        html = src.chapter(0).html
        self.assertIn("<b>", html)
        self.assertIn("<i>", html)
        self.assertIn("<u>", html)
        self.assertIn("color:#C00000", html)
        self.assertIn("font-size:16pt", html)
        self.assertIn("text-align:center", html)
        self.assertIn("</u></i></b></span>", html)
        self.assertEqual(html.count("<b>"), 1)
        self.assertIn("Обычный текст", html)
        src.close()

    def test_pptx_does_not_invent_bold_and_italic(self):
        p = TMP / "plain.pptx"
        slide = '''<?xml version="1.0"?><p:sld
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>
<p:sp><p:txBody><a:p><a:r><a:t>Обычный текст</a:t></a:r></a:p></p:txBody></p:sp>
</p:spTree></p:cSld></p:sld>'''
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("ppt/presentation.xml",
                       "<p:presentation xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'/>")
            z.writestr("ppt/slides/slide1.xml", slide)
        src = formats.open_source(str(p))
        html = src.chapter(0).html
        self.assertIn("Обычный текст", html)
        self.assertNotIn("<b>", html)
        self.assertNotIn("<i>", html)
        src.close()

    def test_pptx_closes_tags_in_reverse_order(self):
        p = TMP / "rich.pptx"
        slide = '''<?xml version="1.0"?><p:sld
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>
<p:sp><p:txBody><a:p><a:r><a:rPr b="1" i="1" sz="2400">
<a:solidFill><a:srgbClr val="3366FF"/></a:solidFill></a:rPr><a:t>Формат</a:t></a:r></a:p>
</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'''
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("ppt/presentation.xml",
                       "<p:presentation xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'/>")
            z.writestr("ppt/slides/slide1.xml", slide)
        src = formats.open_source(str(p))
        html = src.chapter(0).html
        self.assertIn("<b>", html)
        self.assertIn("<i>", html)
        self.assertIn("font-size:24pt", html)
        self.assertIn("color:#3366FF", html)
        self.assertIn("</i></b></span>", html)
        self.assertNotIn("</span></b>", html)
        src.close()

    def test_odp_closes_tags_in_reverse_order(self):
        p = TMP / "rich.odp"
        content = '''<?xml version="1.0"?><office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
<office:automatic-styles><style:style style:name="T1">
<style:paragraph-properties fo:text-align="center"/>
<style:text-properties fo:font-weight="bold" fo:font-style="italic"
 fo:color="#C00000" fo:font-size="16pt" style:text-underline-style="solid"/>
</style:style></office:automatic-styles>
<office:body><office:presentation><draw:page draw:name="Титул">
<text:p text:style-name="T1">Формат ODP</text:p></draw:page>
</office:presentation></office:body></office:document-content>'''
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("content.xml", content)
        src = formats.open_source(str(p))
        html = src.chapter(0).html
        self.assertIn("Формат ODP", html)
        self.assertIn("<b>", html)
        self.assertIn("<i>", html)
        self.assertIn("<u>", html)
        self.assertIn("text-align:center", html)
        self.assertIn("</u></i></b></span>", html)
        self.assertNotIn("</span></b>", html)
        src.close()

    def test_read_meta_skips_office_conversion(self):
        p = TMP / "quick.doc"
        p.write_bytes(b"\xd0\xcf\x11\xe0" + "Быстрый документ".encode("utf-16le"))
        old_docx, old_pptx = formats._fx.office_to_docx, formats._fx.office_to_pptx

        def boom(*args, **kwargs):
            raise AssertionError("read_meta must not call Office COM")

        formats._fx.office_to_docx = boom
        formats._fx.office_to_pptx = boom
        try:
            meta, fmt = formats.read_meta(str(p))
            self.assertEqual(fmt, "doc")
            self.assertTrue(meta.title)
        finally:
            formats._fx.office_to_docx = old_docx
            formats._fx.office_to_pptx = old_pptx

    def test_open_source_no_cover_skips_pdf_conversion(self):
        p = TMP / "nocover.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", '''<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>Текст без обложки</w:t></w:r></w:p></w:body></w:document>''')
        old_pdf = formats._fx.office_to_pdf

        def boom(*args, **kwargs):
            raise AssertionError("open_source_no_cover must skip PDF conversion")

        formats._fx.office_to_pdf = boom
        try:
            src = formats.open_source_no_cover(str(p))
            self.assertIn("Текст без обложки", src.chapter(0).html)
            src.close()
        finally:
            formats._fx.office_to_pdf = old_pdf

    def test_native_path_for_office_com(self):
        if os.name != "nt":
            self.skipTest("Windows only")
        self.assertEqual(formats_extra._native("c:/users/a b/x.doc"),
                         r"c:\users\a b\x.doc")

    def test_invalid_converted_cache_is_rejected(self):
        bad = TMP / "bad.docx"
        bad.write_bytes(b"not a zip")
        good = TMP / "good.docx"
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("word/document.xml", "<x/>")
        self.assertFalse(formats_extra._valid_zip(bad))
        self.assertTrue(formats_extra._valid_zip(good))
        pdf = TMP / "bad.pdf"
        pdf.write_bytes(b"<html>")
        self.assertFalse(formats_extra._valid_pdf(pdf))
        pdf.write_bytes(b"%PDF-1.7\n" + b"x" * 300 + b"\n%%EOF\n")
        self.assertTrue(formats_extra._valid_pdf(pdf))
        pdf.write_bytes(b"%PDF-1.7\ntruncated")
        self.assertFalse(formats_extra._valid_pdf(pdf))

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

    def test_presentations_section_in_tree(self):
        p = TMP / "tree_deck.pptx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("ppt/presentation.xml", "<p:presentation xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'/>")
        win = ui.Win()
        try:
            win.import_path(str(p))
            texts = [win.tree.topLevelItem(i).text(0)
                     for i in range(win.tree.topLevelItemCount())]
            self.assertTrue(any("Презентации" in t for t in texts))
            win.flt = dict(kind="presentations")
            win.reload()
            self.assertGreaterEqual(win.model.rowCount(), 1)
            fmts = {win.model.item(i).data(ui.ROLE)["fmt"]
                    for i in range(win.model.rowCount())}
            self.assertTrue(fmts.issubset(set(common.PRESENTATION_FMTS)))
        finally:
            win.close()

    def test_malformed_office_still_opens_as_text(self):
        p = TMP / "broken.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Текст из повреждённого файла</w:t>")
        src = formats.open_source(str(p))
        self.assertGreaterEqual(src.count, 1)
        self.assertIn("Текст из повреждённого файла", src.chapter(0).html)
        src.close()

    def test_docx_table_keeps_list_tags_inside_cell(self):
        p = TMP / "table_list.docx"
        content = '''<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:tbl><w:tr><w:tc>
<w:p><w:pPr><w:numPr><w:numId w:val="7"/></w:numPr></w:pPr>
<w:r><w:t>В ячейке</w:t></w:r></w:p>
</w:tc></w:tr></w:tbl>
<w:p><w:r><w:t>После таблицы</w:t></w:r></w:p>
</w:body></w:document>'''
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", content)
        src = formats.open_source(str(p))
        html = src.chapter(0).html
        self.assertIn("<td><ul><li>В ячейке</li></ul></td>", html)
        self.assertNotIn("</table></ul>", html)
        src.close()

    def test_pptx_baseline_zero_and_text_color(self):
        p = TMP / "baseline.pptx"
        slide = '''<?xml version="1.0"?><p:sld
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>
<p:sp><p:txBody>
<a:p><a:r><a:rPr baseline="0"/><a:t>Plain</a:t></a:r></a:p>
<a:p><a:r><a:rPr><a:solidFill><a:srgbClr val="3366FF"/></a:solidFill>
<a:ln><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></a:ln></a:rPr>
<a:t>Color</a:t></a:r></a:p>
</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'''
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("ppt/presentation.xml",
                       "<p:presentation xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'/>")
            z.writestr("ppt/slides/slide1.xml", slide)
        src = formats.open_source(str(p))
        html = src.chapter(0).html
        self.assertIn("Plain", html)
        self.assertNotIn("<sub>", html)
        self.assertIn("color:#3366FF", html)
        self.assertNotIn("#FF0000", html)
        src.close()

    def test_valid_zip_checks_expected_member(self):
        p = TMP / "only_types.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("[Content_Types].xml", "<x/>")
        self.assertFalse(formats_extra._valid_zip(p, "word/document.xml"))

    def test_presentation_extensions_registered(self):
        for ext in (".pptx", ".ppt", ".pps", ".ppsx", ".potx", ".odp", ".otp"):
            self.assertIn(ext, formats.ALL_EXTS)

    def test_office_exact_mode_default(self):
        self.assertTrue(common.S.get("office_pdf"))
        for ext in ("docx", "doc", "pptx", "ppt", "odp", "odt", "rtf"):
            self.assertIn(ext, common.OFFICE_FMTS)

    def test_office_faithful_pdf_uses_cache(self):
        p = TMP / "faithful.docx"
        p.write_bytes(b"PK\x03\x04")
        calls = []

        def fake(path, outdir):
            calls.append(path)
            out = Path(outdir) / (Path(path).stem + ".pdf")
            out.write_bytes(b"%PDF-1.7\n" + b"x" * 300 + b"\n%%EOF\n")
            return str(out)

        old = formats_extra.office_to_pdf
        formats_extra.office_to_pdf = fake
        try:
            first = formats_extra.office_faithful_pdf(str(p))
            second = formats_extra.office_faithful_pdf(str(p))
            self.assertEqual(first, second)
            self.assertTrue(first.endswith(".pdf"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(formats_extra.office_faithful_cached(str(p)), first)
        finally:
            formats_extra.office_to_pdf = old

    def test_open_exact_source_falls_back_when_no_converter(self):
        p = TMP / "noconv.pptx"
        p.write_bytes(b"PK\x03\x04")
        old = formats_extra.office_faithful_pdf
        formats_extra.office_faithful_pdf = lambda path: None
        try:
            self.assertIsNone(formats.open_exact_source(str(p)))
        finally:
            formats_extra.office_faithful_pdf = old


class TestReflowFormatting(unittest.TestCase):
    def test_restyle_reapplies_changed_settings(self):
        from PySide6.QtCore import Qt
        p = TMP / "restyle.txt"
        p.write_text("Первый абзац\nВторой абзац", encoding="utf-8")
        src = formats.open_source(str(p))
        st = dict(common.S)
        st.update({"align": "justify", "indent": 12, "para_space": 6})
        view = views.ReflowView(src, st)
        mask = int(Qt.AlignHCenter) | int(Qt.AlignRight) | int(Qt.AlignJustify)
        try:
            view.resize(600, 700)
            view.load(0)
            b = view.doc.begin()
            self.assertEqual(int(b.blockFormat().alignment()) & mask, int(Qt.AlignJustify))
            self.assertAlmostEqual(b.blockFormat().textIndent(), 12.0)

            view.st.update({"align": "left", "indent": 0, "para_space": 0})
            view.restyle()
            b = view.doc.begin()
            self.assertEqual(int(b.blockFormat().alignment()) & mask, 0)
            self.assertAlmostEqual(b.blockFormat().textIndent(), 0.0)
        finally:
            view.close()
            src.close()

    def test_restyle_covers_all_grouped_blocks(self):
        from PySide6.QtCore import Qt
        p = TMP / "restyle_groups.html"
        p.write_text("<html><body><h2>Заголовок</h2><p>Один</p><p>Два</p>"
                     "<p>Три</p></body></html>", encoding="utf-8")
        src = formats.open_source(str(p))
        st = dict(common.S)
        st.update({"align": "justify", "indent": 8})
        view = views.ReflowView(src, st)
        mask = int(Qt.AlignHCenter) | int(Qt.AlignRight) | int(Qt.AlignJustify)
        try:
            view.resize(600, 700)
            view.load(0)
            view.st.update({"align": "left", "indent": 0})
            view.restyle()
            fmts = []
            b = view.doc.begin()
            while b.isValid():
                fmts.append(b.blockFormat())
                b = b.next()
            self.assertGreaterEqual(len(fmts), 4)
            for fm in fmts:
                self.assertEqual(int(fm.alignment()) & mask, 0)
                self.assertAlmostEqual(fm.textIndent(), 0.0)
        finally:
            view.close()
            src.close()


class TestRobustness(unittest.TestCase):
    def test_office_pdf_ignores_cancel_on_close(self):
        from PySide6.QtWidgets import QWidget
        src = TMP / "cancelcase.docx"
        src.write_bytes(b"PK\x03\x04")
        out = TMP / "cancelcase.pdf"
        out.write_bytes(b"%PDF-1.7\n" + b"x" * 300 + b"\n%%EOF\n")
        old_cached = formats_extra.office_faithful_cached
        old_convert = formats_extra.office_faithful_pdf
        old_dialog = reader_mod.QProgressDialog
        formats_extra.office_faithful_cached = lambda path: ""
        formats_extra.office_faithful_pdf = lambda path: str(out)

        class CancelOnClose(old_dialog):
            def close(self):
                self.canceled.emit()
                return super().close()

        reader_mod.QProgressDialog = CancelOnClose
        host = QWidget()
        try:
            self.assertEqual(reader_mod.Reader._office_pdf(host, str(src)), str(out))
        finally:
            reader_mod.QProgressDialog = old_dialog
            formats_extra.office_faithful_cached = old_cached
            formats_extra.office_faithful_pdf = old_convert
            host.close()

    def test_remove_clears_book_tags(self):
        db = TMP / f"tags_{self.id()}.db"
        lib = libmod.Library(path=str(db))
        p = make_book(TMP / f"tags_{self.id()}.fb2", "Книга")
        bid = lib.upsert(dict(path=str(p), fmt="fb2", title="Книга", author="", series="",
                              seq=0, lang="ru", annotation="", genres="",
                              size=p.stat().st_size, mtime=p.stat().st_mtime))
        tid = lib.new_tag("Метка")
        lib.tag_book(tid, bid, True)
        lib.remove(bid)
        self.assertEqual(lib.q("SELECT count(*) c FROM book_tag")[0]["c"], 0)

    def test_global_search_worker(self):
        from PySide6.QtCore import QEventLoop, QTimer
        book = make_book(TMP / "gsearch.fb2", "Поисковая")
        worker = ui._GlobalSearchWorker("Привет", [(777, str(book), "Поисковая")])
        loop = QEventLoop(); results = []
        worker.done.connect(lambda items: (results.append(items), loop.quit()))
        QTimer.singleShot(3000, loop.quit)
        worker.start(); loop.exec(); worker.wait(500)
        self.assertTrue(results and any(row[0] == 777 for row in results[0]))

    def test_settings_dialog_has_tabs(self):
        dlg = ui.SettingsDialog(dict(common.S))
        try:
            self.assertIsNotNone(dlg.tabs.widget(0))
        finally:
            dlg.close()

    def test_all_notes_tolerates_null_note(self):
        db = TMP / f"notesnull_{self.id()}.db"
        lib = libmod.Library(path=str(db))
        p = make_book(TMP / f"notesnull_{self.id()}.fb2", "Заметки")
        bid = lib.upsert(dict(path=str(p), fmt="fb2", title="Заметки", author="", series="",
                              seq=0, lang="ru", annotation="", genres="",
                              size=p.stat().st_size, mtime=p.stat().st_mtime))
        lib.q("INSERT INTO notes(book,chapter,start,end,color,text,note,created,anchor) "
              "VALUES(?,?,?,?,?,?,?,?,?)", (bid, 0, 0, 1, "#fff", "Цитата", None, 0, ""))
        dlg = ui.AllNotesDialog(lib)
        try:
            self.assertEqual(dlg.list.count(), 1)
        finally:
            dlg.close()

    def test_cleanup_faithful_pdfs(self):
        root = Path(common.CACHE) / "exact" / f"cleanup_{self.id()}"
        root.mkdir(parents=True, exist_ok=True)
        content = b"%PDF-1.7\n" + b"x" * 300 + b"\n%%EOF\n"
        old = root / "old.pdf"
        new = root / "new.pdf"
        old.write_bytes(content)
        new.write_bytes(content)
        past = time.time() - 40 * 86400
        os.utime(old, (past, past))
        removed = formats_extra.cleanup_faithful_pdfs(days=30, max_mb=512)
        self.assertGreaterEqual(removed, 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

        for name in ("big1.pdf", "big2.pdf"):
            p = root / name
            with p.open("wb") as f:
                f.truncate(20 * 1024 * 1024)
        removed = formats_extra.cleanup_faithful_pdfs(days=30, max_mb=32)
        self.assertGreaterEqual(removed, 1)
        left = list(root.glob("*.pdf"))
        self.assertLessEqual(sum(p.stat().st_size for p in left), 32 * 1024 * 1024)

    def test_invalidate_faithful_pdf_cache(self):
        p = TMP / f"cachebad_{self.id()}.docx"
        p.write_bytes(b"PK\x03\x04")
        calls = []

        def fake(path, outdir):
            calls.append(path)
            out = Path(outdir) / (Path(path).stem + ".pdf")
            out.write_bytes(b"%PDF-1.7\n" + b"x" * 300 + b"\n%%EOF\n")
            return str(out)

        old = formats_extra.office_to_pdf
        formats_extra.office_to_pdf = fake
        try:
            first = formats_extra.office_faithful_pdf(str(p))
            self.assertTrue(first)
            formats_extra.invalidate_faithful_pdf(str(p))
            self.assertEqual(formats_extra.office_faithful_cached(str(p)), "")
            self.assertTrue(formats_extra.office_faithful_pdf(str(p)))
            self.assertEqual(len(calls), 2)
        finally:
            formats_extra.office_to_pdf = old


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
        bar = self.win.book_tabs.tabBar()
        self.assertEqual(self.win.book_tabs.tabText(ui.HOME_TAB), "Главная")
        self.assertEqual(self.win.book_tabs.tabText(ui.LIB_TAB), "Библиотека")
        self.assertTrue(bar.tabIcon(ui.HOME_TAB).isNull())
        self.assertTrue(bar.tabIcon(ui.LIB_TAB).isNull())
        self.assertIsNone(bar.tabButton(ui.HOME_TAB, QTabBar.RightSide))
        self.assertIsNone(bar.tabButton(ui.LIB_TAB, QTabBar.RightSide))

    def test_invalid_index_signals_do_not_crash(self):
        from PySide6.QtCore import QModelIndex, QPoint
        self.win.list.activated.emit(QModelIndex())
        self.win.list.doubleClicked.emit(QModelIndex())
        self.win.book_menu(QPoint(-1, -1))

    def test_home_has_stats(self):
        self.assertIsNotNone(self.win.home.stats.parent())
        self.assertTrue({"books", "read", "reading", "hours", "pages", "streak", "marks", "notes"}.issubset(
            set(self.win.home.stat_values)))
        self.win.home.refresh()
        for value in self.win.home.stat_values.values():
            self.assertNotEqual(value.text(), "—")

    def test_dialogs_open_inside_main_window(self):
        from PySide6.QtWidgets import QApplication
        before = self.win.book_tabs.count()
        self.win.hotkeys()
        self.assertEqual(self.win.book_tabs.count(), before + 1)
        dlg = self.win.book_tabs.widget(before)
        self.assertIsNotNone(dlg)
        button = self.win.book_tabs.tabBar().tabButton(before, QTabBar.RightSide)
        self.assertIsNotNone(button)
        button.click()
        QApplication.processEvents()
        self.assertEqual(self.win.book_tabs.count(), before)

    def test_keyboard_shortcuts_registered(self):
        from PySide6.QtGui import QShortcut
        keys = {s.key().toString() for s in self.win.findChildren(QShortcut)}
        self.assertIn("F1", keys)
        self.assertIn("Ctrl+L", keys)
        bid = self.win.import_path(str(make_book(TMP / "keys.fb2", "Клавиши")))
        self.win.open_book(bid)
        r = self.win.reader
        try:
            keys |= {s.key().toString() for s in r.findChildren(QShortcut)}
            self.assertIn("Ctrl+Shift+C", keys)
            self.assertIn("Ctrl+G", keys)
        finally:
            r.close()

    def test_tab_close_button_follows_its_widget(self):
        from PySide6.QtWidgets import QApplication
        b1 = self.win.import_path(str(make_book(TMP / "close_a.fb2", "A")))
        b2 = self.win.import_path(str(make_book(TMP / "close_b.fb2", "B")))
        self.win.open_book(b1); r1 = self.win.reader
        self.win.open_book(b2); r2 = self.win.reader
        try:
            i1 = self.win.book_tabs.indexOf(r1)
            self.win.close_tab(i1)
            QApplication.processEvents()
            idx = self.win.book_tabs.indexOf(r2)
            self.assertGreater(idx, ui.LIB_TAB)
            btn = self.win.book_tabs.tabBar().tabButton(idx, QTabBar.RightSide)
            self.assertIsNotNone(btn)
            btn.click()
            QApplication.processEvents()
            self.assertEqual(self.win.book_tabs.indexOf(r2), -1)
        finally:
            for r in (r1, r2):
                idx = self.win.book_tabs.indexOf(r)
                if idx >= 0:
                    self.win.close_tab(idx)
            QApplication.processEvents()

    def test_home_continue_and_recent(self):
        self.win.lib.set_progress(self.bid, 0, 10, 0.4, 10)
        self.win.reload()
        self.assertFalse(self.win.cont.isHidden())
        self.assertEqual(self.win._continue_id, self.bid)
        self.assertFalse(hasattr(self.win.home, "recent_rows"))
        self.assertIsNotNone(self.win.home.stats.parent())

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

    def test_share_quote_and_random_book(self):
        from PySide6.QtWidgets import QApplication
        self.win.open_book(self.bid)
        r = self.win.reader
        r.share_quote()
        self.assertIn("Тестовая книга", QApplication.clipboard().text())
        self.win.open_random_book()
        self.assertIsNotNone(self.win.reader)
        for reader in list(self.win.readers):
            if reader is not r:
                reader.close()
        r.close()

    def test_reopen_closed_tab(self):
        self.win.open_book(self.bid)
        reader = self.win.reader
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
