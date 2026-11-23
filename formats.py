"""Парсеры форматов. Единая модель: Source -> Chapter(title, html, anchors)."""
from __future__ import annotations
import base64, bisect, gzip, hashlib, html, io, os, posixpath, re, shutil, struct, subprocess, threading, weakref, zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from common import CACHE, S

_meta_state = threading.local()
_ZIP_REGISTRY = weakref.WeakSet()


def _open_zip(path):
    z = zipfile.ZipFile(path)
    _ZIP_REGISTRY.add(z)
    return z


def _close_zips(path):
    for z in list(_ZIP_REGISTRY):
        try:
            if str(getattr(z, "filename", "")) == str(path):
                z.close()
        except Exception:
            pass


def _quick_meta():
    return bool(getattr(_meta_state, "quick", False))


def _skip_cover():
    return bool(getattr(_meta_state, "skip_cover", False))


class FormatError(Exception):
    pass


@dataclass
class Meta:
    title: str = ""
    authors: list = field(default_factory=list)
    series: str = ""
    seq: float = 0.0
    lang: str = ""
    annotation: str = ""
    genres: list = field(default_factory=list)
    cover: bytes = b""


@dataclass
class Chapter:
    title: str
    html: str
    anchors: dict = field(default_factory=dict)


class Source:
    fixed = False
    def __init__(self):
        self.meta, self.toc, self.count = Meta(), [], 0
    def chapter(self, i) -> Chapter: ...
    def resource(self, key): return None
    def close(self): pass


def ln(t):  # local-name XML-тега
    return t.split('}')[-1]


def _natural_key(value):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r"(\d+)", value))


def xtext(el):
    return "".join(el.itertext()).strip() if el is not None else ""


_ODF_STYLE = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
_ODF_FO = "{urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0}"


def _odf_format(tp, pp):
    """Inline-теги и CSS из объединённых свойств ODF-стиля."""
    tags, css = [], []
    if tp.get(_ODF_FO + "font-weight") in ("bold", "600", "700", "800", "900"):
        tags.append("b")
    if tp.get(_ODF_FO + "font-style") == "italic":
        tags.append("i")
    if (tp.get(_ODF_STYLE + "text-underline-style") or
            tp.get(_ODF_FO + "text-underline-style")) not in (None, "none"):
        tags.append("u")
    if (tp.get(_ODF_STYLE + "text-line-through-style") or
            tp.get(_ODF_FO + "text-line-through-style")) not in (None, "none"):
        tags.append("s")
    if tp.get(_ODF_FO + "color"):
        css.append("color:" + tp[_ODF_FO + "color"])
    if tp.get(_ODF_FO + "font-size"):
        css.append("font-size:" + tp[_ODF_FO + "font-size"])
    if tp.get(_ODF_FO + "font-family"):
        css.append("font-family:" + tp[_ODF_FO + "font-family"])
    if tp.get(_ODF_FO + "background-color") not in (None, "transparent"):
        css.append("background-color:" + tp[_ODF_FO + "background-color"])
    pos = tp.get(_ODF_STYLE + "text-position", "")
    if pos.startswith("super"):
        tags.append("sup")
    elif pos.startswith("sub"):
        tags.append("sub")
    if pp.get(_ODF_FO + "text-align"):
        css.append("text-align:" + pp[_ODF_FO + "text-align"])
    opens, closes = [], []
    if css:
        opens.append(f'<span style="{html.escape(";".join(css), True)}">')
    for t in tags:
        opens.append(f"<{t}>")
    for t in reversed(tags):
        closes.append(f"</{t}>")
    if css:
        closes.append("</span>")
    return "".join(opens), "".join(closes), ";".join(css)


def _odf_styles(roots):
    """Собрать ODF-стили с наследованием по parent-style-name."""
    raw = {}
    for root in roots:
        for st in root.iter():
            if ln(st.tag) != "style":
                continue
            name = st.get(_ODF_STYLE + "name")
            if not name:
                continue
            entry = raw.setdefault(name, {"parent": "", "tp": {}, "pp": {}})
            parent = st.get(_ODF_STYLE + "parent-style-name")
            if parent:
                entry["parent"] = parent
            tp = next((c for c in st if ln(c.tag) == "text-properties"), None)
            pp = next((c for c in st if ln(c.tag) == "paragraph-properties"), None)
            if tp is not None:
                entry["tp"].update(tp.attrib)
            if pp is not None:
                entry["pp"].update(pp.attrib)
    resolved = {}

    def resolve(name, seen=()):
        if name in resolved:
            return resolved[name]
        if name in seen or name not in raw:
            return {"tp": {}, "pp": {}}
        parent = raw[name]["parent"]
        base = resolve(parent, seen + (name,)) if parent else {"tp": {}, "pp": {}}
        tp = dict(base["tp"]); tp.update(raw[name]["tp"])
        pp = dict(base["pp"]); pp.update(raw[name]["pp"])
        resolved[name] = {"tp": tp, "pp": pp}
        return resolved[name]

    return {name: _odf_format(resolve(name)["tp"], resolve(name)["pp"]) for name in raw}


# ───────────────────────── HTML → подмножество Qt rich text ─────────────────────────
class QtHtml(HTMLParser):
    SKIP = {"script", "style", "head", "noscript", "svg", "form", "input", "button", "select",
            "textarea", "iframe", "object", "embed", "video", "audio", "nav", "link", "meta", "base"}
    H = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    IN = {"b": "b", "strong": "b", "i": "i", "em": "i", "cite": "i", "dfn": "i", "var": "i",
          "u": "u", "ins": "u", "s": "s", "strike": "s", "del": "s", "sub": "sub", "sup": "sup",
          "code": "code", "tt": "code", "kbd": "code", "samp": "code", "small": "small",
          "big": "big", "mark": "mark", "span": "span", "font": "span", "abbr": "span",
          "q": "span", "time": "span", "label": "span"}
    OPENERS = {"<p>", "<li>", "<td>", "<pre>", "<blockquote>", "<br/>",
               "<h1>", "<h2>", "<h3>", "<h4>", "<h5>", "<h6>"}

    def __init__(self, img=None, link=None):
        super().__init__(convert_charrefs=True)
        self.img, self.link = img, link
        self.o, self.pos, self.anchors, self.headings = [], 0, {}, []
        self.skip = self.pre = self.depth = 0
        self.auto = False
        self._div, self._a, self._i, self._hbuf, self._hlvl = [], [], [], None, 0
        self.title_parts, self._t = [], False

    def _o(self, s): self.o.append(s)
    def _ca(self):
        if self.auto:
            self._o("</p>"); self.pos += 1; self.auto = False
    def _need(self):
        if not (self.depth or self.auto):
            self._o("<p>"); self.auto = True

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in self.SKIP:
            self.skip += 1; return
        if self.skip:
            return
        if a.get("id"):
            self.anchors.setdefault(a["id"], self.pos)
        if tag == "a" and a.get("name"):
            self.anchors.setdefault(a["name"], self.pos)
        if tag == "title":
            self._t = True; return
        if tag == "br":
            self._need(); self._o("<br/>"); self.pos += 1; return
        if tag in self.H:
            self._ca(); lvl = self.H[tag]; self._o(f"<h{lvl}>")
            self.depth += 1; self._hbuf, self._hlvl = [], lvl; return
        if tag in ("p", "pre", "blockquote", "li", "dd", "dt"):
            self._ca()
            self._o({"li": "<li>", "blockquote": "<blockquote>", "pre": "<pre>"}.get(tag, "<p>"))
            if tag == "pre":
                self.pre += 1
            self.depth += 1; return
        if tag == "div":
            opened = not (self.depth or self.auto)
            if opened:
                self._o("<p>"); self.auto = True
            self._div.append(opened); return
        if tag in ("ul", "ol"):
            self._ca(); self._o(f"<{tag}>"); return
        if tag == "table":
            self._ca(); self._o('<table border="0" cellpadding="4" cellspacing="0">'); return
        if tag == "tr":
            self._o("<tr>"); return
        if tag in ("td", "th"):
            self._ca(); self._o("<td>"); self.depth += 1; return
        if tag == "hr":
            self._ca(); self._o("<hr/>"); return
        if tag == "img":
            key = self.img(a.get("src") or a.get("data-src") or "") if self.img else None
            if key:
                self._need(); self._o(f'<img src="{html.escape(key, True)}"/>'); self.pos += 1
            return
        if tag == "a":
            href = a.get("href") or a.get("xlink:href") or a.get("l:href") or ""
            tgt = self.link(href) if self.link else None
            self._o(f'<a href="{html.escape(tgt, True)}">' if tgt else "<span>")
            self._a.append(bool(tgt)); return
        if tag in self.IN:
            self._o(f"<{self.IN[tag]}>"); self._i.append(self.IN[tag])

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1); return
        if self.skip:
            return
        if tag == "title":
            self._t = False; return
        if tag in self.H:
            self._ca(); lvl = self.H[tag]; self._o(f"</h{lvl}>"); self.pos += 1
            self.depth = max(0, self.depth - 1)
            if self._hbuf is not None:
                self.headings.append((self._hlvl, self.pos, " ".join("".join(self._hbuf).split())))
                self._hbuf = None
            return
        if tag in ("p", "pre", "blockquote", "li", "dd", "dt", "td", "th"):
            self._ca()
            name = {"li": "li", "blockquote": "blockquote", "pre": "pre",
                    "td": "td", "th": "td"}.get(tag, "p")
            self._o(f"</{name}>"); self.pos += 1
            self.depth = max(0, self.depth - 1)
            if tag == "pre":
                self.pre = max(0, self.pre - 1)
            return
        if tag == "div":
            if self._div and self._div.pop():
                self._ca()
            return
        if tag in ("ul", "ol", "table", "tr"):
            self._ca(); self._o(f"</{tag}>"); return
        if tag == "a":
            self._o("</a>" if (self._a and self._a.pop()) else "</span>"); return
        if tag in self.IN and self._i:
            self._o(f"</{self._i.pop()}>")

    def handle_data(self, data):
        if self.skip:
            return
        if self._t:
            self.title_parts.append(data); return
        if self._hbuf is not None:
            self._hbuf.append(data)
        if not self.pre:
            data = re.sub(r"[ \t\r\n]+", " ", data)
            if not data.strip():
                if (self.depth or self.auto) and self.o and self.o[-1] not in self.OPENERS:
                    self._o(" "); self.pos += 1
                return
        self._need()
        self.pos += len(data); self._o(html.escape(data, False))

    def finish(self):
        self._ca()
        return "".join(self.o), self.anchors, " ".join("".join(self.title_parts).split())


BLOCKEND = re.compile(r"</(p|h[1-6]|li|blockquote|pre|td|div)>")


def plain(h):
    """HTML → текст с сохранением смещений (для поиска/TTS)."""
    out, i = [], 0
    for m in re.finditer(r"<[^>]+>", h):
        out.append(html.unescape(h[i:m.start()]))
        t = m.group(0)
        if t.startswith("<img"):
            out.append("\ufffc")
        elif BLOCKEND.match(t) or t.startswith("<br"):
            out.append("\n")
        i = m.end()
    out.append(html.unescape(h[i:]))
    return "".join(out)


def split_html(h, anchors, headings, limit=180000):
    """Разбиение большого HTML на части с пересчётом смещений."""
    if len(h) <= limit:
        return [("Глава 1", h, anchors)], headings
    cuts, p = [0], 0
    while p < len(h):
        p = h.find("</p>", p + limit)
        p = len(h) if p < 0 else p + 4
        cuts.append(p)
    parts, heads = [], []
    for k in range(len(cuts) - 1):
        a, b = cuts[k], cuts[k + 1]
        seg = h[a:b]
        title = next((t for l, pos, t in headings if a <= pos < b and t), f"Часть {k + 1}")
        parts.append((title, seg, {n: v - a for n, v in anchors.items() if a <= v < b}))
        heads += [(l, pos - a, t) for l, pos, t in headings if a <= pos < b]
    return parts, heads


def html_headings(h):
    """Заголовки из уже готового HTML: (уровень, позиция в HTML, название)."""
    return [(int(m.group(1)), m.start(), plain(m.group(2)).strip())
            for m in re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", h, re.I | re.S)]


def toc_from_headings(h, heads, limit=180000):
    """Содержание по заголовкам: глава + смещение в тексте (pos:N)."""
    cuts = [0]
    p = 0
    while p < len(h):
        p = h.find("</p>", p + limit)
        p = len(h) if p < 0 else p + 4
        cuts.append(p)
    toc = []
    for lvl, pos, title in heads:
        ci = max(0, min(len(cuts) - 2, bisect.bisect_right(cuts, pos) - 1))
        textpos = len(plain(h[cuts[ci]:max(cuts[ci], pos)]).rstrip("\n"))
        toc.append((max(0, min(6, lvl - 1)), title or "…", ci, f"pos:{textpos}"))
    return toc


class Parts(Source):
    """Источник, состоящий из готовых HTML-частей."""
    def __init__(self):
        super().__init__()
        self.parts = []
    def chapter(self, i):
        t, h, a = self.parts[i]
        return Chapter(t, h, a)
    def finalize(self, toc_from_headings=True):
        self.count = len(self.parts)
        if toc_from_headings and not self.toc:
            self.toc = [(0, t, i, "") for i, (t, h, a) in enumerate(self.parts)]


def read_text(path):
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    try:
        from charset_normalizer import from_bytes
        return str(from_bytes(raw).best())
    except Exception:
        for enc in ("cp1251", "koi8-r", "cp866"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
    return raw.decode("latin-1", "replace")


def _hyphen_word(word):
    if len(word) < 6:
        return word
    vowels = "аеёиоуыэюяaeiouy"
    points = []
    for i in range(2, len(word) - 2):
        if word[i] in vowels and word[i + 1] not in vowels:
            points.append(i + 1)
    if not points:
        points = list(range(3, len(word) - 2, 3))
    result, last = [], 0
    for p in points:
        if p - last >= 2 and len(word) - p >= 2:
            result.append(word[last:p])
            last = p
    result.append(word[last:])
    return "\u00ad".join(result)


def soft_hyphenate(text):
    return re.sub(r"[А-Яа-яЁёA-Za-z]{6,}", lambda m: _hyphen_word(m.group(0)), text)


def text_to_html(txt):
    if S.get("hyphenate"):
        txt = soft_hyphenate(txt)
    out = []
    for par in re.split(r"\n\s*\n", txt.replace("\r\n", "\n").replace("\r", "\n")):
        par = par.strip("\n")
        if not par.strip():
            continue
        lines = [l.strip() for l in par.split("\n")]
        short = sum(len(l) for l in lines) / max(1, len(lines)) < 45 and len(lines) > 1
        body = "<br/>".join(html.escape(l) for l in lines) if short else html.escape(" ".join(lines))
        out.append(f"<p>{body}</p>")
    return "".join(out)


HEADRE = re.compile(r"^[ \t]{0,8}((?:глава|часть|книга|chapter|part|book|пролог|эпилог|введение|"
                    r"заключение|послесловие|предисловие)\b[^\n]{0,80}|"
                    r"[IVXLCDM]{1,7}\.?[ \t]*[^\n]{0,60}|\d{1,3}[.)][ \t]*[^\n]{0,60})[ \t]*$",
                    re.I | re.M)


class Txt(Parts):
    def __init__(self, path, txt=None):
        super().__init__()
        txt = txt if txt is not None else read_text(path)
        self.meta.title = Path(path).stem.replace("_", " ").strip()
        marks = [m.start() for m in HEADRE.finditer(txt)]
        chunks = []
        # Двух заголовков достаточно, чтобы разделить книгу на главы.
        if len(marks) >= 2:
            if marks[0] > 200:
                chunks.append((0, "Начало"))
            for k, s in enumerate(marks):
                e = marks[k + 1] if k + 1 < len(marks) else len(txt)
                if e - s > 200:
                    nl = txt.find("\n", s)
                    title = txt[s:nl if nl > 0 else s + 60].strip().rstrip("\r")
                    chunks.append((s, title))
        if len(chunks) < 2:
            chunks, p, n = [], 0, 1
            while p < len(txt):
                e = txt.find("\n\n", p + 18000)
                e = len(txt) if e < 0 else e
                chunks.append((p, f"Часть {n}")); p = e; n += 1
        for idx, (s, title) in enumerate(chunks):
            e = chunks[idx + 1][0] if idx + 1 < len(chunks) else len(txt)
            self.parts.append((title[:90] or f"Часть {idx + 1}", text_to_html(txt[s:e]), {}))
        self.finalize()


def _md_inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\[\^(\w+)\]", r"<sup>\1</sup>", s)
    return s


def md_to_html(text):
    lines = text.splitlines()
    out, in_code, footnotes = [], False, {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            i += 1; continue
        if in_code:
            out.append(html.escape(line)); i += 1; continue
        m = re.match(r"^\s*\[\^(\w+)\]:\s*(.*)$", line)
        if m:
            footnotes[m.group(1)] = m.group(2)
            i += 1; continue
        if re.match(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", line):
            out.append("<hr/>"); i += 1; continue
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
        if m:
            lvl = min(6, len(m.group(1)))
            out.append(f"<h{lvl}>{_md_inline(m.group(2))}</h{lvl}>")
            i += 1; continue
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            rows = []
            while i < len(lines) and "|" in lines[i]:
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><tr>" + "".join(
                f"<td><b>{_md_inline(c)}</b></td>" for c in rows[0]) + "</tr>")
            for row in rows[2:]:
                out.append("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in row) + "</tr>")
            out.append("</table>")
            continue
        if line.lstrip().startswith(">"):
            out.append(f"<blockquote>{_md_inline(line.lstrip()[1:].strip())}</blockquote>")
            i += 1; continue
        m = re.match(r"^\s*[-*+]\s+\[([ xX])\]\s+(.*)$", line)
        if m:
            mark = "☑" if m.group(1).lower() == "x" else "☐"
            out.append(f"<p>{mark} {_md_inline(m.group(2))}</p>")
            i += 1; continue
        m = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$", line)
        if m:
            out.append(f"<p>• {_md_inline(m.group(1))}</p>")
            i += 1; continue
        if line.strip():
            out.append(f"<p>{_md_inline(line)}</p>")
        i += 1
    if in_code:
        out.append("</code></pre>")
    if footnotes:
        out.append("<hr/>")
        for key, value in footnotes.items():
            out.append(f"<p><sup>{key}</sup> {_md_inline(value)}</p>")
    return "\n".join(out)


class Markdown(Parts):
    def __init__(self, path):
        super().__init__()
        body = md_to_html(read_text(path))
        c = QtHtml(img=lambda src: "", link=lambda href: "ext:" + href)
        c.feed(body)
        html_text, anchors, _title = c.finish()
        self.meta.title = Path(path).stem
        self.parts, _ = split_html(html_text, anchors, c.headings)
        self.finalize()
        self.toc = toc_from_headings(html_text, html_headings(html_text)) or self.toc


class HtmlFile(Parts):
    def __init__(self, path):
        super().__init__()
        self.dir = Path(path).parent
        raw = Path(path).read_bytes()
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:2048], re.I)
        txt = raw.decode(m.group(1).decode() if m else "utf-8", "replace")
        c = QtHtml(img=self._img, link=lambda h: ("ext:" + h) if re.match(r"^\w+:", h) else ("go:0#" + h.lstrip("#")))
        c.feed(txt)
        h, anchors, title = c.finish()
        self.meta.title = title or Path(path).stem
        self.parts, _ = split_html(h, anchors, c.headings)
        self.finalize()
        # ReadEra строит содержание по заголовкам даже без оглавления в файле.
        self.toc = toc_from_headings(h, html_headings(h))
        if not self.toc:
            self.toc = [(0, t, i, "") for i, (t, _, _) in enumerate(self.parts)]
    def _img(self, src):
        if src.startswith("data:"):
            return None
        p = (self.dir / unquote(src)).resolve()
        return "file:" + str(p) if p.exists() else None
    def resource(self, key):
        if key.startswith("file:"):
            try:
                return Path(key[5:]).read_bytes()
            except Exception:
                return None


# ───────────────────────── EPUB ─────────────────────────
class Epub(Source):
    def __init__(self, path):
        super().__init__()
        self.zf = _open_zip(path)
        self.names = set(self.zf.namelist())
        self._inline = {}
        cont = ET.fromstring(self.zf.read("META-INF/container.xml"))
        opf = next(e.get("full-path") for e in cont.iter() if ln(e.tag) == "rootfile")
        self.base = posixpath.dirname(opf)
        root = ET.fromstring(self.zf.read(opf))
        man, spine, md, ncx = {}, [], None, None
        for el in root:
            t = ln(el.tag)
            if t == "metadata":
                md = el
            elif t == "manifest":
                for it in el:
                    man[it.get("id")] = (it.get("href", ""), it.get("media-type", ""), it.get("properties", ""))
            elif t == "spine":
                ncx = el.get("toc")
                spine = [it.get("idref") for it in el if it.get("idref") and it.get("linear") != "no"]
        self.spine = [self._res(man[i][0]) for i in spine if i in man and
                      ("html" in man[i][1] or man[i][0].lower().endswith((".html", ".htm", ".xhtml")))]
        self.count = len(self.spine)
        if not self.count:
            raise FormatError("EPUB без spine")
        m, cover_id = self.meta, None
        if md is not None:
            for el in md:
                t, v = ln(el.tag), (el.text or "").strip()
                if t == "title" and not m.title: m.title = v
                elif t == "creator" and v: m.authors.append(v)
                elif t == "language": m.lang = v
                elif t == "description": m.annotation = re.sub("<[^>]+>", "", v)
                elif t == "subject": m.genres.append(v)
                elif t == "meta":
                    if el.get("name") == "calibre:series": m.series = el.get("content", "")
                    elif el.get("name") == "calibre:series_index":
                        try: m.seq = float(el.get("content") or 0)
                        except ValueError: pass
                    elif el.get("property") == "belongs-to-collection": m.series = v
                    elif el.get("name") == "cover": cover_id = el.get("content")
        cand = ([man[cover_id][0]] if cover_id in man else []) + \
               [h for h, mt, pr in man.values() if "cover-image" in pr] + \
               [h for i, (h, mt, pr) in man.items() if "cover" in i.lower() and mt.startswith("image")]
        for h in cand:
            try:
                m.cover = self.zf.read(self._res(h)); break
            except Exception:
                continue
        navs = [i for i, (h, mt, pr) in man.items() if "nav" in pr.split()]
        if navs:
            self._nav(self._res(man[navs[0]][0]))
        else:
            nid = ncx if ncx in man else next((i for i, (h, mt, pr) in man.items() if "ncx" in mt), None)
            if nid:
                self._ncx(self._res(man[nid][0]))
        if not self.toc:
            self.toc = [(0, f"Глава {i+1}", i, "") for i in range(self.count)]
        if not m.title:
            m.title = Path(path).stem

    def _res(self, href):
        return posixpath.normpath(posixpath.join(self.base, unquote(href.split("#")[0])))

    def _target(self, src, cur):
        f, _, frag = src.partition("#")
        p = posixpath.normpath(posixpath.join(posixpath.dirname(cur), unquote(f))) if f else cur
        ch = self.spine.index(p) if p in self.spine else 0
        return ch, unquote(frag)

    def _ncx(self, path):
        try:
            root = ET.fromstring(self.zf.read(path))
        except Exception:
            return
        def walk(el, lvl):
            for np in el:
                if ln(np.tag) != "navPoint":
                    continue
                lab = next((e for e in np.iter() if ln(e.tag) == "text"), None)
                con = next((e for e in np if ln(e.tag) == "content"), None)
                ch, an = self._target(con.get("src", "") if con is not None else "", path)
                self.toc.append((lvl, xtext(lab) or "…", ch, an))
                walk(np, lvl + 1)
        nav = next((e for e in root.iter() if ln(e.tag) == "navMap"), root)
        walk(nav, 0)

    def _nav(self, path):
        try:
            root = ET.fromstring(self.zf.read(path))
        except Exception:
            return
        nav = next((e for e in root.iter() if ln(e.tag) == "nav"), None)
        if nav is None:
            return
        def walk(el, lvl):
            for li in el:
                if ln(li.tag) != "li":
                    continue
                a = next((e for e in li if ln(e.tag) == "a"), None)
                if a is not None:
                    ch, an = self._target(a.get("href", ""), path)
                    self.toc.append((lvl, xtext(a) or "…", ch, an))
                for sub in li:
                    if ln(sub.tag) == "ol":
                        walk(sub, lvl + 1)
        for ol in nav:
            if ln(ol.tag) == "ol":
                walk(ol, 0)

    def chapter(self, i):
        p = self.spine[i]
        raw = self.zf.read(p)
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:2048], re.I)
        c = QtHtml(img=lambda s: self._img(s, p), link=lambda h: self._link(h, p))
        c.feed(raw.decode(m.group(1).decode() if m else "utf-8", "replace"))
        h, anchors, title = c.finish()
        if not title:
            title = next((t for l, pos, t in c.headings if t), f"Глава {i+1}")
        return Chapter(title, h, anchors)

    def _img(self, src, cur):
        if src.startswith("data:"):
            try:
                head, b64 = src.split(",", 1)
                k = f"inline:{len(self._inline)}"
                self._inline[k] = base64.b64decode(b64) if ";base64" in head else unquote(b64).encode()
                return k
            except Exception:
                return None
        p = posixpath.normpath(posixpath.join(posixpath.dirname(cur), unquote(src.split("#")[0])))
        return p if p in self.names else None

    def _link(self, href, cur):
        if re.match(r"^(https?|mailto|ftp):", href):
            return "ext:" + href
        ch, an = self._target(href, cur)
        return f"go:{ch}#{an}"

    def resource(self, key):
        try:
            return self._inline[key] if key.startswith("inline:") else self.zf.read(key)
        except Exception:
            return None

    def close(self):
        self.zf.close()


# ───────────────────────── FB2 ─────────────────────────
class Buf:
    def __init__(self):
        self.o, self.pos, self.anchors = [], 0, {}
    def raw(self, s): self.o.append(s)
    def txt(self, s):
        if s:
            self.o.append(html.escape(s)); self.pos += len(s)
    def open(self, t): self.raw("<" + t + ">")
    def close(self, t): self.raw("</" + t + ">"); self.pos += 1
    def br(self): self.raw("<br/>"); self.pos += 1
    def img(self, k): self.raw(f'<img src="{html.escape(k, True)}"/>'); self.pos += 1
    def anchor(self, n):
        if n:
            self.anchors[n] = self.pos
            self.raw(f'<a name="{html.escape(n, True)}"></a>')
    def html(self): return "".join(self.o)


def fb2_meta(path):
    """Быстрое чтение только <description>."""
    m = Meta()
    data = _fb2_bytes(path)
    try:
        for ev, el in ET.iterparse(io.BytesIO(data), events=("end",)):
            t = ln(el.tag)
            if t == "description":
                _fb2_desc(el, m)
                break
    except Exception:
        pass
    m.title = m.title or Path(path).stem
    return m


def _fb2_bytes(path):
    if Path(path).suffix.lower() in (".zip", ".fbz"):
        with zipfile.ZipFile(path) as z:
            n = next((n for n in z.namelist() if n.lower().endswith(".fb2")), None)
            if not n:
                raise FormatError("В ZIP нет .fb2")
            data = z.read(n)
    else:
        data = Path(path).read_bytes()
    return re.sub(rb"&(?!#?[A-Za-z0-9]+;)", b"&amp;", data)


def _fb2_desc(desc, m):
    ti = next((e for e in desc.iter() if ln(e.tag) == "title-info"), None)
    if ti is None:
        return
    for el in ti:
        t = ln(el.tag)
        if t == "book-title": m.title = xtext(el)
        elif t == "genre": m.genres.append(xtext(el))
        elif t == "lang": m.lang = xtext(el)
        elif t == "annotation": m.annotation = " ".join(xtext(el).split())
        elif t == "author":
            name = " ".join(xtext(el.find("{*}" + k)) for k in ("first-name", "middle-name", "last-name")).strip()
            m.authors.append(name or xtext(el.find("{*}nickname")) or xtext(el))
        elif t == "sequence":
            m.series = el.get("name", "")
            try: m.seq = float(el.get("number") or 0)
            except ValueError: pass
        elif t == "coverpage":
            img = next((e for e in el.iter() if ln(e.tag) == "image"), None)
            if img is not None:
                href = img.get("{http://www.w3.org/1999/xlink}href") or img.get("l:href") or img.get("href") or ""
                m._cover_id = href.lstrip("#")


class Fb2(Source):
    def __init__(self, path):
        super().__init__()
        self.root = ET.fromstring(_fb2_bytes(path))
        self.bins = {b.get("id"): b for b in self.root.iter() if ln(b.tag) == "binary"}
        desc = next((e for e in self.root if ln(e.tag) == "description"), None)
        if desc is not None:
            _fb2_desc(desc, self.meta)
        cid = getattr(self.meta, "_cover_id", None)
        if cid and cid in self.bins:
            try:
                self.meta.cover = base64.b64decode((self.bins[cid].text or "").strip())
            except Exception:
                pass
        self.sections, self.ids, self._n = [], {}, 0
        for body in [b for b in self.root if ln(b.tag) == "body"]:
            secs = [c for c in body if ln(c.tag) == "section"] or [body]
            if body.get("name"):
                self.toc.append((0, {"notes": "Примечания", "comments": "Комментарии"}.get(body.get("name"), body.get("name")),
                                 len(self.sections), ""))
            for s in secs:
                self._reg(s, len(self.sections), 0)
                self.sections.append(s)
        self.count = len(self.sections)
        for i, sec in enumerate(self.sections):
            for e in sec.iter():
                if e.get("id"):
                    self.ids[e.get("id")] = i
        self.meta.title = self.meta.title or Path(path).stem

    def _reg(self, el, ch, lvl):
        aid = f"s{self._n}"; self._n += 1
        el.set("aid", aid)
        self.toc.append((lvl, self._title(el) or f"Раздел {ch+1}", ch, aid))
        for c in el:
            if ln(c.tag) == "section":
                self._reg(c, ch, lvl + 1)

    def _title(self, sec):
        t = next((c for c in sec if ln(c.tag) == "title"), None)
        return " ".join(xtext(t).split())[:120] if t is not None else ""

    def chapter(self, i):
        b = Buf()
        self._block(self.sections[i], b, 1)
        return Chapter(self._title(self.sections[i]) or f"Глава {i+1}", b.html(), b.anchors)

    def _inline(self, el, b):
        if el.get("id"):
            b.anchor(el.get("id"))
        b.txt(el.text or "")
        for c in el:
            t = ln(c.tag)
            wrap = {"emphasis": "i", "strong": "b", "style": "span", "code": "code",
                    "strikethrough": "s", "sub": "sub", "sup": "sup"}.get(t)
            if wrap:
                b.open(wrap); self._inline(c, b); b.raw(f"</{wrap}>")
            elif t == "image":
                k = self._img(c)
                if k: b.img(k)
            elif t == "a":
                href = (c.get("{http://www.w3.org/1999/xlink}href") or c.get("l:href") or c.get("href") or "")
                if href.startswith("#"):
                    tid = href[1:]; ch = self.ids.get(tid, 0)
                    b.raw(f'<a href="go:{ch}#{tid}">'); self._inline(c, b); b.raw("</a>")
                elif re.match(r"^\w+:", href):
                    b.raw(f'<a href="ext:{html.escape(href, True)}">'); self._inline(c, b); b.raw("</a>")
                else:
                    self._inline(c, b)
            else:
                self._inline(c, b)
            b.txt(c.tail or "")

    def _img(self, el):
        href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("l:href") or el.get("href") or ""
        bid = href.lstrip("#")
        return "bin:" + bid if bid in self.bins else None

    def _block(self, el, b, lvl):
        t = ln(el.tag)
        if el.get("id"):
            b.anchor(el.get("id"))
        if t == "section":
            b.anchor(el.get("aid"))
            for c in el:
                self._block(c, b, lvl + 1 if ln(c.tag) == "section" else lvl)
            return
        if t == "title":
            h = min(6, max(1, lvl)); b.open(f"h{h}")
            for c in el:
                if ln(c.tag) in ("p", "subtitle"):
                    self._inline(c, b); b.br()
                elif ln(c.tag) == "empty-line":
                    b.br()
            b.close(f"h{h}"); return
        if t in ("p", "subtitle", "text-author", "date", "td", "th"):
            tag = "h4" if t == "subtitle" else ("td" if t in ("td", "th") else "p")
            b.open(tag); self._inline(el, b); b.close(tag); return
        if t == "empty-line":
            b.open("p"); b.br(); b.close("p"); return
        if t in ("epigraph", "cite", "annotation"):
            b.open("blockquote")
            for c in el:
                self._block(c, b, lvl)
            b.close("blockquote"); return
        if t == "poem":
            for c in el:
                cl = ln(c.tag)
                if cl == "stanza":
                    b.open("p")
                    for v in c:
                        if ln(v.tag) == "v":
                            self._inline(v, b); b.br()
                    b.close("p")
                else:
                    self._block(c, b, lvl)
            return
        if t == "image":
            k = self._img(el)
            if k:
                b.open("p"); b.img(k); b.close("p")
            return
        if t == "table":
            b.raw('<table border="0" cellpadding="4">')
            for tr in el:
                b.raw("<tr>")
                for td in tr:
                    b.open("td"); self._inline(td, b); b.close("td")
                b.raw("</tr>")
            b.raw("</table>"); return
        for c in el:
            self._block(c, b, lvl)

    def resource(self, key):
        if key.startswith("bin:"):
            el = self.bins.get(key[4:])
            if el is not None and el.text:
                try:
                    return base64.b64decode(el.text.strip())
                except Exception:
                    return None


# ───────────────────────── MOBI / PRC / AZW ─────────────────────────
def palmdoc(d):
    out, i, n = bytearray(), 0, len(d)
    while i < n:
        c = d[i]; i += 1
        if c == 0:
            out.append(c)
        elif c <= 8:
            out += d[i:i + c]; i += c
        elif c <= 0x7F:
            out.append(c)
        elif c <= 0xBF:
            if i >= n:
                break
            v = (c << 8) | d[i]; i += 1
            dist, ln_ = (v >> 3) & 0x7FF, (v & 7) + 3
            for _ in range(ln_):
                out.append(out[-dist] if 0 < dist <= len(out) else 0x20)
        else:
            out += bytes((0x20, c ^ 0x80))
    return bytes(out)


class Mobi(Parts):
    def __init__(self, path):
        super().__init__()
        data = Path(path).read_bytes()
        nrec = struct.unpack_from(">H", data, 76)[0]
        offs = [struct.unpack_from(">I", data, 78 + 8 * i)[0] for i in range(nrec)] + [len(data)]
        self.recs = [data[offs[i]:offs[i + 1]] for i in range(nrec)]
        r0 = self.recs[0]
        if r0[16:20] != b"MOBI":
            raise FormatError("Не MOBI")
        comp = struct.unpack_from(">H", r0, 0)[0]
        tlen = struct.unpack_from(">I", r0, 4)[0]
        ntext = struct.unpack_from(">H", r0, 8)[0]
        hlen = struct.unpack_from(">I", r0, 20)[0]
        enc = struct.unpack_from(">I", r0, 28)[0]
        first_img = struct.unpack_from(">I", r0, 0x6C)[0]
        exth = struct.unpack_from(">I", r0, 0x80)[0]
        if comp == 17480:
            raise FormatError("HUFF/CDIC (AZW3): установите пакет 'mobi' (pip install mobi)")
        if comp not in (1, 2):
            raise FormatError(f"Сжатие {comp} не поддержано (возможно DRM)")
        cp = "utf-8" if enc == 65001 else "cp1252"
        raw = b"".join(palmdoc(self.recs[i]) if comp == 2 else self.recs[i] for i in range(1, ntext + 1))[:tlen]
        text = raw.decode(cp, "replace")
        fno, fnl = struct.unpack_from(">II", r0, 0x54)
        self.meta.title = r0[fno:fno + fnl].decode(cp, "replace").strip() or Path(path).stem
        if exth & 0x40:
            p = 16 + hlen
            if r0[p:p + 4] == b"EXTH":
                cnt = struct.unpack_from(">I", r0, p + 8)[0]; q = p + 12
                cov = None
                for _ in range(cnt):
                    t, l = struct.unpack_from(">II", r0, q); v = r0[q + 8:q + l]; q += l
                    s = v.decode(cp, "replace")
                    if t == 100: self.meta.authors.append(s)
                    elif t == 503: self.meta.title = s
                    elif t == 105: self.meta.genres.append(s)
                    elif t == 103: self.meta.annotation = re.sub("<[^>]+>", "", s)
                    elif t == 524: self.meta.lang = s
                    elif t == 201: cov = struct.unpack(">I", v)[0] if len(v) == 4 else None
                if cov is not None and cov != 0xFFFFFFFF:
                    idx = first_img + cov
                    if idx < len(self.recs):
                        self.meta.cover = self.recs[idx]
        if not self.meta.cover and first_img < len(self.recs):
            self.meta.cover = self.recs[first_img]
        text = re.sub(r'<img([^>]*?)recindex="(\d+)"([^>]*?)>',
                      lambda m: f'<img src="mobi:{first_img + int(m.group(2)) - 1}">', text, flags=re.I)
        chunks = re.split(r"<mbp:pagebreak\s*/?>", text, flags=re.I)
        if len(chunks) < 2:
            chunks, p = [], 0
            while p < len(text):
                e = text.find("</p>", p + 60000)
                e = len(text) if e < 0 else e + 4
                chunks.append(text[p:e]); p = e
        for k, ch in enumerate(chunks):
            if not ch.strip():
                continue
            c = QtHtml(img=lambda s: s if s.startswith("mobi:") else None,
                       link=lambda h: ("ext:" + h) if re.match(r"^\w+:", h) else f"go:0#{h.lstrip('#')}")
            c.feed(ch)
            h, anchors, title = c.finish()
            if not title:
                title = next((t for l, pos, t in c.headings if t), f"Часть {k+1}")
            self.parts.append((title[:90], h, anchors))
        self.finalize()

    def resource(self, key):
        if key.startswith("mobi:"):
            i = int(key[5:])
            if 0 <= i < len(self.recs):
                return self.recs[i]


# ───────────────────────── DOCX / ODT / RTF / DOC / CHM / CBZ ─────────────────────────
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class Docx(Parts):
    def __init__(self, path):
        super().__init__()
        self.z = _open_zip(path)
        rels = {}
        try:
            for r in ET.fromstring(self.z.read("word/_rels/document.xml.rels")):
                rels[r.get("Id")] = r.get("Target", "")
        except Exception:
            pass
        try:
            core = ET.fromstring(self.z.read("docProps/core.xml"))
            for e in core:
                t = ln(e.tag)
                if t == "title": self.meta.title = xtext(e)
                elif t == "creator": self.meta.authors = [xtext(e)]
                elif t == "description": self.meta.annotation = xtext(e)
        except Exception:
            pass
        styles = {}
        try:
            sroot = ET.fromstring(self.z.read("word/styles.xml"))
            for st in sroot:
                if ln(st.tag) != "style":
                    continue
                sid = st.get(W + "styleId")
                if not sid:
                    continue
                nm = next((c for c in st if ln(c.tag) == "name"), None)
                based = next((c for c in st if ln(c.tag) == "basedOn"), None)
                styles[sid] = {
                    "name": (nm.get(W + "val") if nm is not None else sid) or sid,
                    "based": based.get(W + "val") if based is not None else "",
                    "rpr": next((c for c in st if ln(c.tag) == "rPr"), None),
                    "ppr": next((c for c in st if ln(c.tag) == "pPr"), None),
                }
        except Exception:
            pass

        def style_chain(sid):
            seen = set()
            while sid and sid not in seen and sid in styles:
                seen.add(sid)
                yield sid
                sid = styles[sid]["based"]

        def merge_elems(*groups):
            merged, order = {}, []
            for group in groups:
                for c in group or []:
                    t = ln(c.tag)
                    if t not in merged:
                        order.append(t)
                    merged[t] = c
            return [merged[t] for t in order]

        def style_rpr(sid):
            groups = [list(styles[s]["rpr"]) if styles[s]["rpr"] is not None else []
                      for s in reversed(list(style_chain(sid)))]
            return merge_elems(*groups)

        def style_ppr(sid):
            groups = [list(styles[s]["ppr"]) if styles[s]["ppr"] is not None else []
                      for s in reversed(list(style_chain(sid)))]
            return merge_elems(*groups)

        def heading_level(sid, ppr):
            names = []
            for s in style_chain(sid):
                names.append(styles[s]["name"] or "")
                names.append(s)
            if sid and sid not in names:
                names.append(sid)
            for name in names:
                name = name.lower()
                m = re.search(r"(?:heading|заголовок|title|название)\s*(\d)", name)
                if m:
                    return min(6, int(m.group(1)))
                if "title" in name or "название" in name:
                    return 1
            lvl = next((c for c in ppr if ln(c.tag) == "outlineLvl"), None)
            if lvl is not None:
                try:
                    return min(6, int(lvl.get(W + "val")) + 1)
                except (TypeError, ValueError):
                    pass
            return 0

        doc = ET.fromstring(self.z.read("word/document.xml"))
        body = next(e for e in doc if ln(e.tag) == "body")
        out, pos = [], 0

        def emit(s, txtlen=0, block=False):
            nonlocal pos
            out.append(s); pos += txtlen + (1 if block else 0)

        def rpr_tags(items):
            tags, css = [], []
            for c in items or []:
                t, val = ln(c.tag), c.get(W + "val")
                if t == "b":
                    if val not in ("0", "false", "off"):
                        tags.append("b")
                elif t == "i":
                    if val not in ("0", "false", "off"):
                        tags.append("i")
                elif t == "u":
                    if val not in ("none", "0", "off"):
                        tags.append("u")
                elif t == "strike":
                    if val not in ("0", "false", "off"):
                        tags.append("s")
                elif t == "vertAlign":
                    if val == "superscript":
                        tags.append("sup")
                    elif val == "subscript":
                        tags.append("sub")
                elif t == "color" and val and val.lower() != "auto":
                    css.append("color:#" + re.sub(r"[^0-9a-fA-F]", "", val)[:6])
                elif t == "sz" and val:
                    try:
                        css.append(f"font-size:{int(val) / 2:.0f}pt")
                    except ValueError:
                        pass
                elif t == "rFonts":
                    face = c.get(W + "ascii") or c.get(W + "hAnsi")
                    if face:
                        css.append("font-family:'" + face.replace("'", "") + "'")
                elif t in ("highlight", "shd"):
                    fill = re.sub(r"[^0-9a-fA-F]", "", val or c.get(W + "fill") or "")
                    if fill:
                        css.append("background-color:#" + fill[:6])
            opens, closes = [], []
            if css:
                opens.append(f'<span style="{html.escape(";".join(css), True)}">')
            for t in tags:
                opens.append(f"<{t}>")
            for t in reversed(tags):
                closes.append(f"</{t}>")
            if css:
                closes.append("</span>")
            return "".join(opens), "".join(closes)

        def pstyle(ppr):
            css = []
            jc = next((c for c in ppr if ln(c.tag) == "jc"), None)
            if jc is not None and jc.get(W + "val") in ("center", "right", "both"):
                v = jc.get(W + "val")
                css.append("text-align:" + ("justify" if v == "both" else v))
            sp = next((c for c in ppr if ln(c.tag) == "spacing"), None)
            if sp is not None:
                for key, prop in (("before", "margin-top"), ("after", "margin-bottom")):
                    val = sp.get(W + key)
                    if val:
                        try:
                            css.append(f"{prop}:{int(val) / 20:.0f}pt")
                        except ValueError:
                            pass
            ind = next((c for c in ppr if ln(c.tag) == "ind"), None)
            if ind is not None:
                left = ind.get(W + "left") or ind.get(W + "start")
                if left:
                    try:
                        css.append(f"margin-left:{int(left) / 20:.0f}pt")
                    except ValueError:
                        pass
                first = ind.get(W + "firstLine")
                if first:
                    try:
                        css.append(f"text-indent:{int(first) / 20:.0f}pt")
                    except ValueError:
                        pass
            return f' style="{html.escape(";".join(css), True)}"' if css else ""

        def list_id(ppr):
            numpr = next((c for c in ppr if ln(c.tag) == "numPr"), None)
            if numpr is None:
                return None
            num = next((c for c in numpr if ln(c.tag) == "numId"), None)
            return num.get(W + "val") if num is not None else "0"

        def run(r, para_style=""):
            rpr = next((c for c in r if ln(c.tag) == "rPr"), None)
            if rpr is not None and any(
                    ln(c.tag) in ("vanish", "webHidden") and c.get(W + "val") not in ("0", "false", "off")
                    for c in rpr):
                return
            rstyle = next((c for c in rpr if ln(c.tag) == "rStyle"), None) if rpr is not None else None
            char_style = rstyle.get(W + "val") if rstyle is not None else ""
            items = merge_elems(style_rpr(para_style), style_rpr(char_style),
                                list(rpr) if rpr is not None else [])
            open_tags, close_tags = rpr_tags(items)
            emit(open_tags)
            extent = next((c for c in r.iter() if ln(c.tag) == "extent"), None)
            iw = ih = 0
            if extent is not None:
                try:
                    iw = max(1, round(int(extent.get("cx", 0)) / 9525))
                    ih = max(1, round(int(extent.get("cy", 0)) / 9525))
                except ValueError:
                    pass
            for c in r.iter():
                t = ln(c.tag)
                if t == "t":
                    s = c.text or ""
                    emit(html.escape(s), len(s))
                elif t == "br":
                    emit("<br/><br/>" if c.get(W + "type") == "page" else "<br/>", 1)
                elif t == "tab":
                    emit("    ", 4)
                elif t == "noBreakHyphen":
                    emit("‑", 1)
                elif t == "softHyphen":
                    emit("", 0)
                elif t == "blip":
                    rid = c.get(REL + "embed")
                    tgt = rels.get(rid, "")
                    if tgt:
                        tgt = tgt.lstrip("/")
                        zpath = posixpath.normpath(posixpath.join("word", tgt)) \
                            if not tgt.startswith("word/") else tgt
                        size = f' width="{iw}" height="{ih}"' if iw and ih else ""
                        emit(f'<img src="z:{html.escape(zpath, True)}"{size}/>', 1)
            emit(close_tags)

        def emit_runs(container, para_style):
            for c in container:
                t = ln(c.tag)
                if t == "r":
                    run(c, para_style)
                elif t == "hyperlink":
                    href = rels.get(c.get(REL + "id"), "")
                    if href:
                        emit(f'<a href="ext:{html.escape(href, True)}">')
                    emit_runs(c, para_style)
                    if href:
                        emit("</a>")
                elif t in ("ins", "smartTag", "sdt", "sdtContent", "fldSimple", "customXml"):
                    emit_runs(c, para_style)

        cur_list = None

        def emit_para(el):
            nonlocal cur_list
            direct = next((c for c in el if ln(c.tag) == "pPr"), None)
            style = ""
            if direct is not None:
                ps = next((c for c in direct if ln(c.tag) == "pStyle"), None)
                style = ps.get(W + "val", "") if ps is not None else ""
            ppr = merge_elems(style_ppr(style), list(direct) if direct is not None else [])
            lvl = heading_level(style, ppr)
            lid = list_id(ppr)
            if lid != cur_list:
                if cur_list is not None:
                    emit("</ul>")
                if lid is not None:
                    emit("<ul>")
                cur_list = lid
            tag = f"h{lvl}" if lvl else ("li" if lid is not None else "p")
            emit(f"<{tag}{pstyle(ppr)}>")
            emit_runs(el, style)
            emit(f"</{tag}>", block=True)

        def emit_table(tbl):
            nonlocal cur_list
            outer_list = cur_list
            cur_list = None
            emit('<table border="0" cellpadding="4" cellspacing="0">')
            for tr in tbl:
                if ln(tr.tag) != "tr":
                    continue
                emit("<tr>")
                for tc in tr:
                    if ln(tc.tag) != "tc":
                        continue
                    emit("<td>")
                    for child in tc:
                        if ln(child.tag) == "p":
                            emit_para(child)
                        elif ln(child.tag) == "tbl":
                            emit_table(child)
                    if cur_list is not None:
                        emit("</ul>")
                        cur_list = None
                    emit("</td>")
                emit("</tr>")
            emit("</table>")
            cur_list = outer_list

        for el in body:
            t = ln(el.tag)
            if t == "p":
                emit_para(el)
            elif t == "tbl":
                if cur_list is not None:
                    emit("</ul>")
                    cur_list = None
                emit_table(el)
        if cur_list is not None:
            emit("</ul>")
        h = "".join(out)
        self.parts, _ = split_html(h, {}, [], 180000)
        self.meta.title = self.meta.title or Path(path).stem
        self.finalize()
        self.toc = toc_from_headings(h, html_headings(h))

    def resource(self, key):
        if key.startswith("z:"):
            try:
                return self.z.read(key[2:])
            except Exception:
                return None


class Odt(Parts):
    def __init__(self, path):
        super().__init__()
        self.z = _open_zip(path)
        root = ET.fromstring(self.z.read("content.xml"))
        tns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
        xlink = "{http://www.w3.org/1999/xlink}"

        roots = [root]
        try:
            roots.append(ET.fromstring(self.z.read("styles.xml")))
        except Exception:
            pass
        styles = _odf_styles(roots)

        out = []

        def inline(el):
            if el.text:
                out.append(html.escape(el.text))
            for c in el:
                t = ln(c.tag)
                if t == "span":
                    op, cl, css = styles.get(c.get(tns + "style-name"), ("", "", ""))
                    style = f' style="{html.escape(css, True)}"' if css else ""
                    out.append(f"<span{style}>{op}")
                    inline(c)
                    out.append(f"{cl}</span>")
                elif t == "line-break":
                    out.append("<br/>")
                elif t == "tab":
                    out.append("    ")
                elif t == "s":
                    out.append(" " * int(c.get(tns + "c") or 1))
                elif t == "image":
                    href = c.get(xlink + "href", "")
                    if href:
                        out.append(f'<img src="z:{html.escape(href, True)}"/>')
                elif t == "a":
                    href = c.get(xlink + "href", "")
                    out.append(f'<a href="ext:{html.escape(href, True)}">')
                    inline(c)
                    out.append("</a>")
                elif t in ("note", "annotation", "bookmark", "bookmark-start",
                           "bookmark-end", "soft-page-break"):
                    pass
                else:
                    inline(c)
                if c.tail:
                    out.append(html.escape(c.tail))

        def walk(el):
            t = ln(el.tag)
            if t == "list":
                out.append("<ul>")
                for c in el:
                    walk(c)
                out.append("</ul>")
            elif t == "list-item":
                out.append("<li>")
                for c in el:
                    if ln(c.tag) in ("p", "h"):
                        inline(c)
                    else:
                        walk(c)
                out.append("</li>")
            elif t in ("p", "h"):
                op, cl, css = styles.get(el.get(tns + "style-name"), ("", "", ""))
                style = f' style="{html.escape(css, True)}"' if css else ""
                if t == "h":
                    try:
                        lvl = int(el.get(tns + "outline-level") or 1)
                    except ValueError:
                        lvl = 1
                    tag = f"h{min(6, max(1, lvl))}"
                else:
                    tag = "p"
                out.append(f"<{tag}{style}>{op}")
                inline(el)
                out.append(f"{cl}</{tag}>")
            elif t == "table":
                out.append('<table border="0" cellpadding="4">')
                for c in el:
                    walk(c)
                out.append("</table>")
            elif t == "table-row":
                out.append("<tr>")
                for c in el:
                    walk(c)
                out.append("</tr>")
            elif t == "table-cell":
                out.append("<td>")
                for c in el:
                    walk(c)
                out.append("</td>")
            elif t == "image":
                href = el.get(xlink + "href", "")
                if href:
                    out.append(f'<img src="z:{html.escape(href, True)}"/>')
            else:
                if el.text:
                    out.append(html.escape(el.text))
                for c in el:
                    walk(c)
                    if c.tail:
                        out.append(html.escape(c.tail))

        text = next(e for e in root.iter() if ln(e.tag) == "text")
        for c in text:
            walk(c)
        h = "".join(out)
        self.parts, _ = split_html(h, {}, [])
        self.meta.title = Path(path).stem
        self.finalize()
        self.toc = toc_from_headings(h, html_headings(h))

    def resource(self, key):
        if key.startswith("z:"):
            try:
                return self.z.read(key[2:])
            except Exception:
                return None


def rtf_to_text(data):
    out, i, n = [], 0, len(data)
    skip, uc, cp, bold = 0, 1, "cp1251", 0
    dest_skip = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "listtable", "listoverridetable",
                 "generator", "themedata", "colorschememapping", "datastore", "xmlnstbl", "field", "fldinst"}
    stack = []
    while i < n:
        ch = data[i:i + 1]
        if ch == b"{":
            stack.append(skip); i += 1; continue
        if ch == b"}":
            skip = stack.pop() if stack else 0; i += 1; continue
        if ch == b"\\":
            m = re.match(rb"\\([a-zA-Z]+)(-?\d+)?[ ]?", data[i:])
            if m:
                w, arg = m.group(1).decode(), m.group(2)
                i += m.end()
                if w in dest_skip or (w == "*" ):
                    skip += 1
                elif w == "ansicpg" and arg: cp = "cp" + arg.decode()
                elif w == "uc" and arg: uc = int(arg)
                elif w == "u" and arg:
                    if not skip: out.append(chr(int(arg) % 65536))
                    i += uc
                elif w in ("par", "line", "sect", "page"):
                    if not skip: out.append("\n")
                elif w == "tab":
                    if not skip: out.append("\t")
                elif w in ("emdash", "endash"):
                    if not skip: out.append("—" if w == "emdash" else "–")
                continue
            m = re.match(rb"\\'([0-9a-fA-F]{2})", data[i:])
            if m:
                if not skip:
                    out.append(bytes.fromhex(m.group(1).decode()).decode(cp, "replace"))
                i += m.end(); continue
            i += 2; continue
        if ch in (b"\r", b"\n"):
            i += 1; continue
        j = i
        while j < n and data[j:j + 1] not in (b"\\", b"{", b"}", b"\r", b"\n"):
            j += 1
        if not skip:
            out.append(data[i:j].decode(cp, "replace"))
        i = j
    return re.sub(r"\n{3,}", "\n\n", "".join(out))


class Rtf(Txt):
    def __init__(self, path):
        super().__init__(path, rtf_to_text(Path(path).read_bytes()))


class Doc(Txt):
    def __init__(self, path):
        raw = Path(path).read_bytes()
        if raw[:2] == b"PK":
            # Файл с расширением .doc, но внутри обычный OOXML.
            src = Docx(path)
            self.parts, self.meta, self.toc, self.count = src.parts, src.meta, src.toc, src.count
            self.resource = src.resource
            return
        if raw.lstrip().startswith(b"{\\rtf"):
            super().__init__(path, rtf_to_text(raw))
            return

        txt = ""
        exe = shutil.which("antiword") or shutil.which("catdoc")
        if exe:
            try:
                args = [exe, "-w", "0", path] if "antiword" in exe.lower() else [exe, path]
                txt = subprocess.run(args, capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
            except Exception:
                txt = ""
        if not txt.strip():
            txt = _fx.legacy_office_text(path)
        if not txt.strip():
            raise FormatError("DOC: не удалось извлечь текст. Установите LibreOffice/antiword "
                              "или пересохраните файл в .docx")
        super().__init__(path, txt)


class Chm(Parts):
    def __init__(self, path):
        super().__init__()
        exe = shutil.which("7z") or shutil.which("7za") or shutil.which("7zr")
        if not exe:
            raise FormatError("Для .CHM нужен 7z (p7zip-full)")
        self.tmp = CACHE / ("chm_" + re.sub(r"\W", "_", Path(path).stem)[:40])
        if not self.tmp.exists():
            self.tmp.mkdir(parents=True, exist_ok=True)
            subprocess.run([exe, "x", "-y", f"-o{self.tmp}", path], capture_output=True, timeout=180)
        files = sorted(str(p) for p in self.tmp.rglob("*") if p.suffix.lower() in (".htm", ".html"))
        hhc = next(self.tmp.rglob("*.hhc"), None)
        order = []
        if hhc:
            for m in re.finditer(r'name="(?:Name|Local)"\s+value="([^"]+)"', hhc.read_text("utf-8", "replace"), re.I):
                v = m.group(1)
                if v.lower().endswith((".htm", ".html")):
                    hit = next((f for f in files if f.replace("\\", "/").endswith(v.replace("\\", "/"))), None)
                    if hit and hit not in order:
                        order.append(hit)
        for f in files:
            if f not in order:
                order.append(f)
        for f in order:
            c = QtHtml(img=lambda s, f=f: "file:" + str((Path(f).parent / unquote(s)).resolve()),
                       link=lambda h: ("ext:" + h) if re.match(r"^\w+:", h) else None)
            c.feed(Path(f).read_bytes().decode("utf-8", "replace"))
            h, a, t = c.finish()
            if h.strip():
                self.parts.append((t or Path(f).stem, h, a))
        self.meta.title = Path(path).stem
        self.finalize()

    def resource(self, key):
        if key.startswith("file:"):
            try:
                return Path(key[5:]).read_bytes()
            except Exception:
                return None

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Cbz(Parts):
    def __init__(self, path):
        super().__init__()
        self.z = _open_zip(path)
        imgs = sorted((n for n in self.z.namelist()
                       if n.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))),
                      key=_natural_key)
        if not imgs:
            raise FormatError("В архиве нет изображений")
        for n in imgs:
            self.parts.append((Path(n).stem, f'<p align="center"><img src="z:{n}"/></p>', {}))
        self.meta.title = Path(path).stem
        self.meta.cover = self.z.read(imgs[0])
        self.finalize()

    def resource(self, key):
        if key.startswith("z:"):
            try:
                return self.z.read(key[2:])
            except Exception:
                return None


# ───────────────────────── PDF / DJVU (fixed layout) ─────────────────────────
class Pdf(Source):
    fixed = True
    def __init__(self, path, title=None):
        super().__init__()
        from PySide6.QtCore import Qt, QModelIndex, QByteArray, QBuffer, QIODevice
        from PySide6.QtGui import QImage
        from PySide6.QtPdf import QPdfDocument, QPdfBookmarkModel
        self.Qt = Qt
        self.doc = QPdfDocument()
        if self.doc.load(str(path)) != QPdfDocument.Error.None_:
            raise FormatError("PDF не открыт (повреждён или защищён паролем)")
        self.count = self.doc.pageCount()
        F = QPdfDocument.MetaDataField
        self.meta.title = title or (self.doc.metaData(F.Title) or "") or Path(path).stem
        au = self.doc.metaData(F.Author) or ""
        self.meta.authors = [a.strip() for a in re.split(r"[;,]", au) if a.strip()]
        self.meta.annotation = self.doc.metaData(F.Subject) or ""
        try:
            img = self.doc.render(0, self.page_size(0).toSize() * 0.4)
            if not img.isNull():
                ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly)
                img.save(buf, "PNG"); self.meta.cover = bytes(ba)
        except Exception:
            pass
        try:
            m = QPdfBookmarkModel(); m.setDocument(self.doc)
            Role = getattr(QPdfBookmarkModel, "Role", None)
            PageRole = getattr(Role, "Page",
                               getattr(QPdfBookmarkModel, "PageRole", Qt.UserRole + 1))
            def walk(parent, lvl):
                for r in range(m.rowCount(parent)):
                    idx = m.index(r, 0, parent)
                    self.toc.append((lvl, str(idx.data(Qt.DisplayRole) or "…"), 0, int(idx.data(PageRole) or 0)))
                    walk(idx, lvl + 1)
            walk(QModelIndex(), 0)
        except Exception:
            pass

    def page_size(self, p):
        for name in ("pagePointSize", "pageSize"):
            fn = getattr(self.doc, name, None)
            if fn is not None:
                try:
                    s = fn(p)
                    if s is not None and not s.isEmpty():
                        return s
                except Exception:
                    pass
        from PySide6.QtCore import QSizeF
        return QSizeF(595.0, 842.0)   # fallback: A4 в пунктах
    def render(self, p, size, options=None):
        from PySide6.QtPdf import QPdfDocumentRenderOptions
        return self.doc.render(p, size, options or QPdfDocumentRenderOptions())
    def text(self, p):
        try:
            return self.doc.getAllText(p).text()
        except Exception:
            return ""
    def close(self):
        self.doc.close()


class Djvu(Pdf):
    def __init__(self, path):
        exe = shutil.which("ddjvu")
        if not exe:
            raise FormatError("Для DJVU нужен DjVuLibre (ddjvu)")
        st = Path(path).stat()
        key = re.sub(r"\W", "_", Path(path).stem)[:40] + f"_{int(st.st_mtime)}_{st.st_size}.pdf"
        out = CACHE / key
        if not out.exists():
            r = subprocess.run([exe, "-format=pdf", "-quality=85", str(path), str(out)],
                               capture_output=True, timeout=900)
            if not out.exists():
                raise FormatError("ddjvu: " + r.stderr.decode("utf-8", "replace")[:200])
        super().__init__(str(out), title=Path(path).stem)


# ───────────────────────── диспетчер ─────────────────────────
def open_source(path) -> Source:
    p = str(path)
    ext = Path(p).suffix.lower()
    if not Path(p).is_file():
        raise FormatError("Файл не найден")
    try:
        if ext == ".epub": return Epub(p)
        if ext in (".fb2", ".fbz"): return Fb2(p)
        if ext == ".zip":
            with zipfile.ZipFile(p) as z:
                fb2 = any(n.lower().endswith(".fb2") for n in z.namelist())
            return Fb2(p) if fb2 else Cbz(p)
        if ext == ".cbz": return Cbz(p)
        if ext in (".txt", ".text", ".log"): return Txt(p)
        if ext == ".md": return Markdown(p)
        if ext in (".html", ".htm", ".xhtml"): return HtmlFile(p)
        if ext == ".docx": return Docx(p)
        if ext == ".odt": return Odt(p)
        if ext == ".rtf": return Rtf(p)
        if ext == ".doc": return Doc(p)
        if ext == ".chm": return Chm(p)
        if ext == ".pdf": return Pdf(p)
        if ext in (".djvu", ".djv"): return Djvu(p)
        if ext in (".mobi", ".prc", ".pdb", ".azw", ".azw3"):
            try:
                return Mobi(p)
            except FormatError:
                try:
                    import mobi
                    tmp, extracted = mobi.extract(p)
                    src = open_source(extracted)
                    src._tmp = tmp
                    return src
                except ImportError:
                    raise FormatError("AZW3/HUFF-CDIC: pip install mobi")
        raise FormatError(f"Формат {ext} не поддержан")
    except FormatError:
        raise
    except Exception as e:
        raise FormatError(f"{type(e).__name__}: {e}")


def read_meta(path):
    ext = Path(path).suffix.lower()
    if ext in (".fb2", ".fbz", ".zip"):
        try:
            m = fb2_meta(path)
            if m.title:
                return m, "fb2"
        except Exception:
            pass
    _meta_state.quick = True
    _meta_state.skip_cover = True
    s = None
    try:
        s = open_source(path)
        m = s.meta
    finally:
        if s is not None:
            s.close()
        _meta_state.quick = False
        _meta_state.skip_cover = False
    return m, ext.lstrip(".")


def open_source_no_cover(path):
    """Открыть книгу без генерации обложки: она нужна только библиотеке."""
    _meta_state.skip_cover = True
    try:
        return open_source(path)
    finally:
        _meta_state.skip_cover = False


def open_exact_source(path):
    """Office-файл с точной вёрсткой: конвертация в PDF и открытие в PDF-режиме."""
    pdf = _fx.office_faithful_pdf(path)
    if not pdf:
        return None
    try:
        return open_source(pdf)
    except Exception:
        return None

# ══════════ Совместимость Qt6 и качество рендера ══════════
from common import PDF_LOCK as _PDF_LOCK


def _pdf_page_size(self, p):
    from PySide6.QtCore import QSizeF
    for name in ("pagePointSize", "pageSize"):
        fn = getattr(self.doc, name, None)
        if fn is None:
            continue
        try:
            s = fn(int(p))
            if s is not None and not s.isEmpty():
                return QSizeF(s)
        except Exception:
            continue
    return QSizeF(595.0, 842.0)


def _pdf_render(self, p, size, options=None):
    from PySide6.QtPdf import QPdfDocumentRenderOptions
    o = options
    if o is None:
        o = QPdfDocumentRenderOptions()
        try:
            F = QPdfDocumentRenderOptions.RenderFlag
            o.setRenderFlags(F.Annotations | F.FormFields)
        except Exception:
            pass
    with _PDF_LOCK:
        return self.doc.render(int(p), size, o)


def _pdf_text(self, p):
    with _PDF_LOCK:
        try:
            return self.doc.getAllText(int(p)).text()
        except Exception:
            return ""


def _pdf_init(orig):
    def __init__(self, path, title=None):
        orig(self, path, title)
        self.path = str(path)
        if not self.meta.cover and self.count:
            try:
                from PySide6.QtCore import QSize, QByteArray, QBuffer, QIODevice
                ps = self.page_size(0)
                w = 340
                h = max(1, int(w * ps.height() / max(1.0, ps.width())))
                img = self.render(0, QSize(w, min(510, h)))
                if not img.isNull():
                    ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly)
                    img.save(buf, "PNG")
                    self.meta.cover = bytes(ba)
            except Exception:
                pass
    return __init__


Pdf.page_size = _pdf_page_size
Pdf.render = _pdf_render
Pdf.text = _pdf_text
Pdf.__init__ = _pdf_init(Pdf.__init__)


def _qt_app():
    try:
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()
    except Exception:
        return None


def _qt_main_thread():
    app = _qt_app()
    if app is None:
        return False
    try:
        from PySide6.QtCore import QThread
        return QThread.currentThread() is app.thread()
    except Exception:
        return False


def _render_pdf_cover(pdf_path):
    """Снять PNG с первой страницы настоящего PDF."""
    if _qt_app() is None:
        return b""
    try:
        from PySide6.QtCore import QSize, QByteArray, QBuffer, QIODevice
        from PySide6.QtPdf import QPdfDocument
        pdf = QPdfDocument()
        if pdf.load(str(pdf_path)) != QPdfDocument.Error.None_ or not pdf.pageCount():
            return b""
        img = pdf.render(0, QSize(340, 480))
        if img.isNull():
            return b""
        ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG"); buf.close()
        return bytes(ba)
    except Exception:
        return b""


def _first_page_cover(src, path, title=""):
    """Обложка = титульная/первая страница, а не первая попавшаяся картинка."""
    if _skip_cover():
        return b""
    from common import CACHE
    try:
        stat = Path(path).stat()
        key = hashlib.md5(f"{path}|{stat.st_mtime}|{stat.st_size}".encode()).hexdigest()[:16]
        out = CACHE / ("cover_" + key)
        real = _fx.office_to_pdf(path, out)
        if real:
            data = _render_pdf_cover(real)
            if data:
                return data
    except Exception:
        pass

    if not _qt_main_thread():
        return b""

    # Fallback без внешних утилит: собираем титул из первого фрагмента текста.
    tmp = None
    try:
        from PySide6.QtCore import QSize, QByteArray, QBuffer, QIODevice
        from PySide6.QtGui import QTextDocument, QFont, QPageSize, QPdfWriter

        doc = QTextDocument()
        doc.setDefaultFont(QFont("Sans", 12))
        doc.setDefaultStyleSheet(
            "body{color:#000000;} h1,h2,h3{color:#000000;}"
            "p{margin:0 0 6px 0;}")
        name = html.escape(title or src.meta.title or "")
        doc.setHtml(f"<h1>{name}</h1>" + (src.chapter(0).html[:12000] if src.count else ""))
        doc.setPageSize(QSize(595, 842))
        doc.setDocumentMargin(48)

        ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly)
        writer = QPdfWriter(buf)
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setResolution(120)
        doc.print_(writer)
        buf.close()

        data = bytes(ba)
        tmp = CACHE / f"_cover_{hashlib.md5(data).hexdigest()[:16]}.pdf"
        tmp.write_bytes(data)
        return _render_pdf_cover(tmp)
    except Exception:
        return b""
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def _docx_cover(orig):
    def __init__(self, path):
        orig(self, path)
        if not self.meta.cover:
            self.meta.cover = _first_page_cover(self, path)
    return __init__


Docx.__init__ = _docx_cover(Docx.__init__)


def _odt_cover(orig):
    def __init__(self, path):
        orig(self, path)
        if not self.meta.cover:
            self.meta.cover = _first_page_cover(self, path)
    return __init__


Odt.__init__ = _odt_cover(Odt.__init__)

# ══════════ Расширение форматов: Windows-пути без внешних зависимостей ══════════
import re as _re
from pathlib import Path as _P
import formats_extra as _fx


class Presentation(Parts):
    """Слайд-шоу как последовательность глав: PPTX/POTX/PPSX и ODP/OTP."""
    def __init__(self, path):
        super().__init__()
        ext = _P(path).suffix.lower()
        self.z = _open_zip(path)
        try:
            core = ET.fromstring(self.z.read("docProps/core.xml"))
            for e in core:
                t = ln(e.tag)
                if t == "title": self.meta.title = xtext(e)
                elif t == "creator": self.meta.authors = [xtext(e)]
                elif t == "description": self.meta.annotation = xtext(e)
        except Exception:
            pass
        if ext in (".odp", ".otp"):
            self._odp()
        else:
            self._pptx()
        self.meta.title = self.meta.title or _P(path).stem
        if not self.parts:
            self.parts.append((self.meta.title,
                               f"<p>{html.escape(self.meta.title)}</p>", {}))
        self.finalize()

    @staticmethod
    def _pptx_run(r):
        rpr = next((c for c in r if ln(c.tag) == "rPr"), None)
        tags, css = [], []
        if rpr is not None:
            if rpr.get("b") in ("1", "true", "on"):
                tags.append("b")
            if rpr.get("i") in ("1", "true", "on"):
                tags.append("i")
            if rpr.get("u") not in (None, "none", "0"):
                tags.append("u")
            if rpr.get("strike") not in (None, "noStrike", "0"):
                tags.append("s")
            base = rpr.get("baseline")
            if base:
                try:
                    delta = int(base)
                    if delta:
                        tags.append("sup" if delta > 0 else "sub")
                except ValueError:
                    pass
            if rpr.get("sz"):
                try:
                    css.append(f"font-size:{int(rpr.get('sz')) / 100:.0f}pt")
                except ValueError:
                    pass
            for c in rpr:
                t = ln(c.tag)
                if t == "solidFill":
                    color = next((x.get("val") for x in c
                                  if ln(x.tag) == "srgbClr" and x.get("val")), None)
                    if color:
                        css.append("color:#" + re.sub(r"[^0-9a-fA-F]", "", color)[:6])
                elif t == "latin" and c.get("typeface"):
                    css.append("font-family:'" + c.get("typeface").replace("'", "") + "'")
        opens, closes = [], []
        if css:
            opens.append(f'<span style="{html.escape(";".join(css), True)}">')
        for t in tags:
            opens.append(f"<{t}>")
        for t in reversed(tags):
            closes.append(f"</{t}>")
        if css:
            closes.append("</span>")
        text = "".join(t.text or "" for t in r.iter() if ln(t.tag) == "t")
        return "".join(opens) + html.escape(text) + "".join(closes)

    @staticmethod
    def _pptx_plain(p):
        return "".join(t.text or "" for t in p.iter() if ln(t.tag) == "t").strip()

    def _pptx_para(self, p):
        ppr = next((c for c in p if ln(c.tag) == "pPr"), None)
        css = []
        if ppr is not None:
            algn = ppr.get("algn")
            if algn in ("ctr", "r", "just", "justLow"):
                css.append("text-align:" + ("center" if algn == "ctr" else
                                            "right" if algn == "r" else "justify"))
        parts = []
        for c in p:
            t = ln(c.tag)
            if t in ("r", "fld"):
                parts.append(self._pptx_run(c))
            elif t == "br":
                parts.append("<br/>")
        if ppr is not None and any(ln(c.tag) in ("buChar", "buAutoNum") for c in ppr):
            parts.insert(0, "• ")
        style = f' style="{";".join(css)}"' if css else ""
        return style, "".join(parts)

    def _slide(self, number, title, blocks, images, notes="", rich=False, title_html=None):
        html_parts = [title_html or f"<h1>{html.escape(title or f'Слайд {number}')}</h1>"]
        html_parts += [x if rich else f"<p>{html.escape(x)}</p>" for x in blocks if x.strip()]
        html_parts += [f'<img src="z:{html.escape(x, True)}"/>' for x in images]
        if notes.strip():
            html_parts.append(f"<p><i>Заметки: {html.escape(notes.strip())}</i></p>")
        self.parts.append((title[:90] or f"Слайд {number}", "".join(html_parts), {}))
        self.toc.append((0, title[:90] or f"Слайд {number}", number - 1, ""))

    def _pptx(self):
        names = set(self.z.namelist())
        rels = {}
        try:
            for r in ET.fromstring(self.z.read("ppt/_rels/presentation.xml.rels")):
                rels[r.get("Id")] = r.get("Target", "")
        except Exception:
            pass
        slides = []
        try:
            pres = ET.fromstring(self.z.read("ppt/presentation.xml"))
            lst = next((e for e in pres.iter() if ln(e.tag) == "sldIdLst"), None)
            if lst is not None:
                for s in lst:
                    target = rels.get(s.get(REL + "id"), "")
                    if target:
                        slides.append(posixpath.normpath(posixpath.join("ppt", target.lstrip("/"))))
        except Exception:
            pass
        if not slides:
            slides = sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n))
        for i, slide in enumerate(slides, 1):
            if slide not in names:
                continue
            root = ET.fromstring(self.z.read(slide))
            srels = {}
            relpath = posixpath.join(posixpath.dirname(slide), "_rels",
                                     posixpath.basename(slide) + ".rels")
            if relpath in names:
                try:
                    for r in ET.fromstring(self.z.read(relpath)):
                        srels[r.get("Id")] = r.get("Target", "")
                except Exception:
                    pass
            items = []
            for sp in root.iter():
                if ln(sp.tag) != "sp":
                    continue
                ph = next((e for e in sp.iter() if ln(e.tag) == "ph"), None)
                typ = (ph.get("type") if ph is not None else "") or "body"
                for p in sp.iter():
                    if ln(p.tag) == "p" and self._pptx_plain(p):
                        items.append((typ in ("title", "ctrTitle"), p))
            if not items:
                for p in root.iter():
                    if ln(p.tag) == "p" and self._pptx_plain(p):
                        items.append((False, p))

            blocks = []
            title_html = None
            title_text = ""
            for is_title, p in items:
                style, runs = self._pptx_para(p)
                if not runs.strip():
                    continue
                if is_title and title_html is None:
                    title_html = f"<h2{style}>{runs}</h2>"
                    title_text = self._pptx_plain(p)
                else:
                    tag = "h3" if is_title else "p"
                    blocks.append(f"<{tag}{style}>{runs}</{tag}>")
            if title_html is None and blocks:
                first = blocks.pop(0)
                title_html = re.sub(r"^<p([^>]*)>", r"<h2\1>", first).replace("</p>", "</h2>")
                title_text = plain(title_html)
            images = []
            for blip in root.iter():
                if ln(blip.tag) != "blip":
                    continue
                target = srels.get(blip.get(REL + "embed"), "")
                if target:
                    images.append(posixpath.normpath(
                        posixpath.join(posixpath.dirname(slide), target.lstrip("/"))))
            notes = ""
            note_path = f"ppt/notesSlides/notesSlide{i}.xml"
            if note_path in names:
                try:
                    nroot = ET.fromstring(self.z.read(note_path))
                    notes = " ".join(t.text or "" for t in nroot.iter() if ln(t.tag) == "t")
                except Exception:
                    pass
            self._slide(i, title_text or f"Слайд {i}", blocks, images, notes,
                        rich=True, title_html=title_html)

    def _odp(self):
        root = ET.fromstring(self.z.read("content.xml"))
        draw = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
        xlink = "{http://www.w3.org/1999/xlink}"
        tns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"

        roots = [root]
        try:
            roots.append(ET.fromstring(self.z.read("styles.xml")))
        except Exception:
            pass
        styles = _odf_styles(roots)

        def inline(el):
            out = []
            if el.text:
                out.append(html.escape(el.text))
            for c in el:
                t = ln(c.tag)
                if t == "span":
                    op, cl, css = styles.get(c.get(tns + "style-name"), ("", "", ""))
                    style = f' style="{html.escape(css, True)}"' if css else ""
                    out.append(f"<span{style}>{op}{inline(c)}{cl}</span>")
                elif t == "line-break":
                    out.append("<br/>")
                elif t == "tab":
                    out.append("    ")
                elif t == "s":
                    out.append(" " * int(c.get(tns + "c") or 1))
                elif t == "a":
                    href = c.get(xlink + "href", "")
                    out.append(f'<a href="ext:{html.escape(href, True)}">{inline(c)}</a>')
                elif t == "image":
                    href = c.get(xlink + "href", "")
                    if href:
                        out.append(f'<img src="z:{html.escape(href, True)}"/>')
                elif t in ("note", "annotation", "tracked-changes", "soft-page-break"):
                    pass
                else:
                    out.append(inline(c))
                if c.tail:
                    out.append(html.escape(c.tail))
            return "".join(out)

        pages = [e for e in root.iter() if ln(e.tag) == "page"]
        if not pages:
            return
        for i, page in enumerate(pages, 1):
            blocks, images = [], []
            title_text = ""

            def walk(el):
                nonlocal title_text
                t = ln(el.tag)
                if t == "list":
                    blocks.append("<ul>")
                    for c in el:
                        walk(c)
                    blocks.append("</ul>")
                elif t == "list-item":
                    blocks.append("<li>")
                    for c in el:
                        if ln(c.tag) in ("p", "h"):
                            blocks.append(inline(c))
                        else:
                            walk(c)
                    blocks.append("</li>")
                elif t in ("p", "h"):
                    content = inline(el)
                    if not plain(content).strip():
                        return
                    op, cl, css = styles.get(el.get(tns + "style-name"), ("", "", ""))
                    style = f' style="{html.escape(css, True)}"' if css else ""
                    if t == "h":
                        try:
                            lvl = int(el.get(tns + "outline-level") or 1)
                        except ValueError:
                            lvl = 1
                        tag = f"h{min(6, max(1, lvl))}"
                    else:
                        tag = "p"
                    if not title_text:
                        title_text = plain(content).strip()
                    blocks.append(f"<{tag}{style}>{op}{content}{cl}</{tag}>")
                elif t == "image":
                    href = el.get(xlink + "href", "")
                    if href:
                        images.append(href)
                else:
                    for c in el:
                        walk(c)

            walk(page)
            title = page.get(draw + "name") or title_text or f"Слайд {i}"
            if re.fullmatch(r"(page|Slide|Слайд)?\d*", title or "", re.I):
                title = title_text or f"Слайд {i}"
            self._slide(i, title, blocks, images, rich=True)

    def resource(self, key):
        if key.startswith("z:"):
            try:
                return self.z.read(key[2:])
            except Exception:
                return None

    def close(self):
        self.z.close()


def _presentation_cover(orig):
    def __init__(self, path):
        orig(self, path)
        if not self.meta.cover:
            self.meta.cover = _first_page_cover(self, path)
    return __init__


Presentation.__init__ = _presentation_cover(Presentation.__init__)


class OfficePresentation(Presentation):
    """PPT/PPS: PPTX через LibreOffice, иначе встроенный текстовый fallback."""
    def __init__(self, path):
        raw = _P(path).read_bytes()
        if raw[:2] == b"PK":
            super().__init__(path)
            self._title_from_slide(path, path)
            return
        key = hashlib.md5(str(_P(path).resolve()).encode()).hexdigest()[:10] + f"_{int(_P(path).stat().st_mtime)}"
        out = CACHE / ("conv_ppt_" + key)
        pptx = None if _quick_meta() else _fx.office_to_pptx(path, out)
        if pptx:
            super().__init__(pptx)
            self._title_from_slide(path, pptx)
            return

        slides = _fx.legacy_ppt_slides(path)
        if slides:
            Parts.__init__(self)
            for i, lines in enumerate(slides, 1):
                title = lines[0] if lines else f"Слайд {i}"
                body = lines[1:]
                html_parts = [f"<h1>{html.escape(title)}</h1>"]
                html_parts += [f"<p>{html.escape(x)}</p>" for x in body if x.strip()]
                self.parts.append((title[:90] or f"Слайд {i}", "".join(html_parts), {}))
            self.finalize()
            self.meta.title = self.meta.title or (slides[0][0] if slides[0] else _P(path).stem)
            return

        text = _fx.legacy_office_text(path)
        if not text.strip():
            raise FormatError("PPT/PPS: не удалось извлечь текст. Установите PowerPoint/LibreOffice "
                              "или пересохраните файл в .pptx")
        Parts.__init__(self)
        t = Txt(path, text)
        self.parts, self.toc, self.count = t.parts, t.toc, t.count
        self.meta.title = self.meta.title or _P(path).stem

    def _title_from_slide(self, orig, source):
        title = (self.meta.title or "").strip()
        generic = (not title or re.match(r"^(слайд|slide)\s*\d*$", title, re.I)
                   or title.lower() == _P(source).stem.lower())
        if generic:
            self.meta.title = (self.parts[0][0] if self.parts else "") or _P(orig).stem

    def close(self):
        if hasattr(self, "z"):
            self.z.close()


class ChmAny(Parts):
    def __init__(self, path):
        super().__init__()
        self.tmp = CACHE / ("chm_" + _re.sub(r"\W", "_", _P(path).stem)[:40])
        if not self.tmp.exists() or not any(self.tmp.rglob("*.htm*")):
            self.tmp.mkdir(parents=True, exist_ok=True)
            if not _fx.decompile_chm(path, self.tmp):
                raise FormatError("CHM: нужен 7-Zip (на Windows достаточно штатного hh.exe)")
        files = sorted(str(p) for p in self.tmp.rglob("*") if p.suffix.lower() in (".htm", ".html"))
        order = []
        hhc = next(self.tmp.rglob("*.hhc"), None)
        if hhc:
            for m in _re.finditer(r'name="(?:Name|Local)"\s+value="([^"]+)"',
                                  hhc.read_text("utf-8", "replace"), _re.I):
                v = m.group(1).replace("\\", "/")
                if v.lower().endswith((".htm", ".html")):
                    hit = next((f for f in files if f.replace("\\", "/").endswith(v)), None)
                    if hit and hit not in order:
                        order.append(hit)
        order += [f for f in files if f not in order]
        for f in order:
            c = QtHtml(img=lambda s, f=f: "file:" + str((_P(f).parent / unquote(s)).resolve()),
                       link=lambda h: ("ext:" + h) if _re.match(r"^\w+:", h) else None)
            c.feed(_P(f).read_bytes().decode("utf-8", "replace"))
            h, a, t = c.finish()
            if h.strip():
                self.parts.append((t or _P(f).stem, h, a))
        if not self.parts:
            raise FormatError("CHM: не найдено HTML-содержимое")
        self.meta.title = _P(path).stem
        self.finalize()

    def resource(self, key):
        if key.startswith("file:"):
            try:
                return _P(key[5:]).read_bytes()
            except Exception:
                return None


class OfficeDoc(Parts):
    def __init__(self, path):
        super().__init__()
        raw = _P(path).read_bytes()
        if raw[:2] == b"PK":
            try:
                with zipfile.ZipFile(path) as z:
                    names = z.namelist()
                if "word/document.xml" in names:
                    src = Docx(path)
                    self.parts, self.meta, self.toc, self.count = src.parts, src.meta, src.toc, src.count
                    self.resource = src.resource
                    self.meta.title = self.meta.title or _P(path).stem
                    return
                if "content.xml" in names:
                    src = Odt(path)
                    self.parts, self.meta, self.toc, self.count = src.parts, src.meta, src.toc, src.count
                    self.resource = src.resource
                    self.meta.title = self.meta.title or _P(path).stem
                    return
            except Exception:
                pass
        key = hashlib.md5(str(_P(path).resolve()).encode()).hexdigest()[:10] + f"_{int(_P(path).stat().st_mtime)}"
        out = CACHE / ("conv_" + key)
        docx = None if _quick_meta() else _fx.office_to_docx(path, out)
        if docx:
            src = Docx(docx)
            self.parts, self.meta, self.toc, self.count = src.parts, src.meta, src.toc, src.count
            self.resource = src.resource
            self.meta.title = self.meta.title or _P(path).stem
            return
        txt = None if _quick_meta() else _fx.office_to_text(path)
        if not txt or not txt.strip():
            txt = _fx.legacy_office_text(path)
        if not txt or not txt.strip():
            raise FormatError("DOC: не удалось извлечь текст. Установите Word/LibreOffice/antiword "
                              "или пересохраните файл в .docx")
        t = Txt(path, txt)
        self.parts, self.meta, self.toc, self.count = t.parts, t.meta, t.toc, t.count
        self.meta.title = self.meta.title or _P(path).stem


class ComicAny(Parts):
    def __init__(self, path):
        super().__init__()
        ext = _P(path).suffix.lower()
        self.z = None
        self.tmp = None
        if ext == ".cbz":
            self.z = _open_zip(path)
            names = sorted((n for n in self.z.namelist() if n.lower().endswith(
                (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))), key=_natural_key)
            self._files = None
        else:
            self.tmp = CACHE / ("cb_" + _re.sub(r"\W", "_", _P(path).stem)[:40])
            if not self.tmp.exists():
                if not _fx.extract_archive(path, self.tmp):
                    raise FormatError("CBR/CB7/CBT: нужен 7-Zip")
            names = sorted((str(p) for p in self.tmp.rglob("*") if p.suffix.lower() in
                            (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")), key=_natural_key)
            self._files = names
        if not names:
            raise FormatError("В архиве нет изображений")
        for i, n in enumerate(names):
            k = f"z:{n}" if self.z else f"file:{n}"
            self.parts.append((_P(n).stem, f'<p align="center"><img src="{html.escape(k, True)}"/></p>', {}))
        self.meta.title = _P(path).stem
        try:
            self.meta.cover = self.resource("z:" + names[0] if self.z else "file:" + names[0]) or b""
        except Exception:
            pass
        self.finalize()

    def resource(self, key):
        try:
            if key.startswith("z:") and self.z:
                return self.z.read(key[2:])
            if key.startswith("file:"):
                return _P(key[5:]).read_bytes()
        except Exception:
            return None

    def close(self):
        if self.z:
            self.z.close()


class Fb3(Source):
    _block = Fb2._block
    _inline = Fb2._inline

    def __init__(self, path):
        super().__init__()
        self.z = _open_zip(path)
        self.bins, self.ids = {}, {}
        xmls = [n for n in self.z.namelist() if n.lower().endswith(".xml")]
        # Библиотека изображений лежит в <binary> внутри XML-частей.
        for n in xmls:
            try:
                xr = ET.fromstring(self.z.read(n))
            except Exception:
                continue
            for e in xr.iter():
                if ln(e.tag) == "binary" and e.get("id"):
                    self.bins[e.get("id")] = e
        desc = next((n for n in xmls if "description" in n.lower()), None)
        bodies = [n for n in xmls if _P(n).name.lower().startswith("body")]
        if desc:
            try:
                d = ET.fromstring(self.z.read(desc))
                for e in d.iter():
                    t = ln(e.tag)
                    if t == "book-title": self.meta.title = xtext(e)
                    elif t == "author":
                        self.meta.authors.append(" ".join(
                            xtext(e.find("{*}" + k)) for k in ("first-name", "last-name")).strip()
                            or xtext(e))
                    elif t == "annotation": self.meta.annotation = " ".join(xtext(e).split())
                    elif t == "lang": self.meta.lang = xtext(e)
                    elif t == "sequence":
                        self.meta.series = e.get("name", "")
            except Exception:
                pass
        if not bodies:
            bodies = [n for n in xmls if n != desc]
        self.sections = []
        for n in bodies:
            try:
                root = ET.fromstring(self.z.read(n))
            except Exception:
                continue
            secs = [c for c in root if ln(c.tag) == "section"] or [root]
            for s in secs:
                self.sections.append(s)
        if not self.sections:
            raise FormatError("FB3: не найдено тело книги")
        self.count = len(self.sections)
        self._n = 0
        for i, s in enumerate(self.sections):
            self._reg(s, i, 0)
        for i, s in enumerate(self.sections):
            for e in s.iter():
                if e.get("id"):
                    self.ids[e.get("id")] = i
        cover = next((n for n in self.z.namelist()
                      if "cover" in _P(n).name.lower() and
                      n.lower().endswith((".jpg", ".jpeg", ".png"))), None)
        if cover:
            self.meta.cover = self.z.read(cover)
        self.meta.title = self.meta.title or _P(path).stem

    def _title(self, sec):
        t = next((c for c in sec if ln(c.tag) == "title"), None)
        return " ".join(xtext(t).split())[:120] if t is not None else ""

    def _reg(self, el, ch, lvl):
        aid = f"s{self._n}"; self._n += 1
        el.set("aid", aid)
        self.toc.append((lvl, self._title(el) or f"Раздел {ch + 1}", ch, aid))
        for c in el:
            if ln(c.tag) == "section":
                self._reg(c, ch, lvl + 1)

    def chapter(self, i):
        b = Buf()
        self._block(self.sections[i], b, 1)
        return Chapter(self._title(self.sections[i]) or f"Глава {i + 1}", b.html(), b.anchors)

    def _img(self, el):
        href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or el.get("src") or ""
        href = href.lstrip("#")
        if href in self.bins:
            return "bin:" + href
        name = next((n for n in self.z.namelist() if n == href or _P(n).name == _P(href).name), None)
        return "z:" + name if name else None

    def resource(self, key):
        try:
            if key.startswith("z:"):
                return self.z.read(key[2:])
            if key.startswith("bin:"):
                el = self.bins.get(key[4:])
                if el is not None and el.text:
                    return base64.b64decode(el.text.strip())
        except Exception:
            return None

    def close(self):
        self.z.close()


_BASE_EXTS = {".epub", ".fb2", ".fbz", ".zip", ".txt", ".md", ".html", ".htm", ".xhtml",
              ".mobi", ".prc", ".azw", ".azw3", ".pdf", ".djvu", ".djv", ".docx", ".odt",
              ".rtf", ".doc", ".chm", ".cbz", ".text", ".log", ".pdb"}
ALL_EXTS = _BASE_EXTS | _fx.EXTRA_EXTS

_orig_open = open_source

def _office_text_fallback(path):
    """Если сложный парсер не справился — вытащить хоть текст, а не падать ошибкой."""
    try:
        parts = []
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    if not name.lower().endswith((".xml", ".rels")):
                        continue
                    low = name.lower()
                    if not any(k in low for k in ("document", "slide", "content", "notes", "styles")):
                        continue
                    raw = z.read(name).decode("utf-8", "replace")
                    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
                    text = re.sub(r"\s{2,}", " ", text).strip()
                    if text:
                        parts.append(text)
        else:
            text = _fx.legacy_office_text(path)
            if text.strip():
                parts.append(text)
        if parts:
            return Txt(path, "\n".join(parts))
    except Exception:
        pass
    return None


def open_source(path):  # noqa: F811 — расширенный диспетчер
    p = str(path)
    ext = _P(p).suffix.lower()
    if ext == ".chm":
        return ChmAny(p)
    if ext in (".doc", ".docm", ".dotx", ".ott") or \
            ext in (".pptx", ".potx", ".ppsx", ".odp", ".otp", ".ppt", ".pps") or \
            ext in (".docx", ".odt"):
        try:
            if ext in (".doc", ".docm", ".dotx", ".ott"):
                return OfficeDoc(p)
            if ext in (".pptx", ".potx", ".ppsx", ".odp", ".otp"):
                return Presentation(p)
            if ext in (".ppt", ".pps"):
                return OfficePresentation(p)
            return _orig_open(p)
        except Exception as exc:
            _close_zips(p)
            src = _office_text_fallback(p)
            if src is None:
                raise exc
            return src
    if ext in (".cbr", ".cb7", ".cbt", ".cbz"):
        return ComicAny(p)
    if ext == ".fb3":
        return Fb3(p)
    if ext == ".rar":
        return _archive_source(p)
    if ext == ".zip":
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
        low = [n.lower() for n in names]
        if any(n.endswith(".fb2") for n in low):
            return Fb2(p)
        if any(n.endswith(".epub") for n in low):
            inner = next(n for n in names if n.lower().endswith(".epub"))
            return _zip_inner(p, inner)
        if any(n.endswith((".txt", ".md")) for n in low):
            inner = next(n for n in names if n.lower().endswith((".txt", ".md")))
            return _zip_inner(p, inner)
        if any(n.endswith((".html", ".htm", ".xhtml")) for n in low):
            inner = next(n for n in names if n.lower().endswith((".html", ".htm", ".xhtml")))
            return _zip_inner(p, inner)
        return ComicAny(p) if any(n.endswith((".jpg", ".png", ".jpeg")) for n in low) \
            else _orig_open(p)
    return _orig_open(p)


def _archive_source(path):
    """RAR и другие архивы: распаковываем и открываем первую книгу внутри."""
    import hashlib
    stat = _P(path).stat()
    key = hashlib.md5((str(path) + str(stat.st_mtime) + str(stat.st_size)).encode("utf-8")).hexdigest()[:16]
    dest = CACHE / ("arc_" + key)
    if not (dest.is_dir() and any(dest.rglob("*"))):
        if not _fx.extract_archive(path, dest):
            raise FormatError("Архив: нужен 7-Zip (или UnRAR)")
    prio = (".fb2", ".epub", ".pdf", ".txt", ".docx", ".html", ".djvu", ".mobi", ".rtf",
            ".odt", ".pptx", ".odp", ".ppt")
    files = [p for p in dest.rglob("*") if p.is_file() and p.suffix.lower() in _BASE_EXTS]
    if not files:
        raise FormatError("В архиве не найдено книг")
    files.sort(key=lambda p: (prio.index(p.suffix.lower()) if p.suffix.lower() in prio else 99,
                              str(p).lower()))
    return _orig_open(str(files[0]))


def _zip_inner(path, inner):
    import hashlib
    key = hashlib.md5((str(path) + inner).encode("utf-8")).hexdigest()[:16]
    dest = CACHE / ("zip_" + key)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / _P(inner).name
    if not out.is_file():
        with zipfile.ZipFile(path) as z:
            out.write_bytes(z.read(inner))
    return _orig_open(str(out))