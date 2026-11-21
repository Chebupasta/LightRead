"""TTS (Qt TextToSpeech) и офлайн-словарь StarDict."""
import base64, gzip, re, struct, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from PySide6.QtCore import QObject, Signal


class Tts(QObject):
    stateChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.e = None
        self._cfg = None
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
            self.e = QTextToSpeech(self)
            self.e.stateChanged.connect(lambda s: self.stateChanged.emit(str(s)))
        except Exception:
            pass

    def ok(self):
        return self.e is not None and bool(self.e.availableVoices())

    def voices(self):
        return [v.name() for v in self.e.availableVoices()] if self.e else []

    def configure(self, st):
        if not self.e:
            return
        cfg = tuple(st.get(k) for k in ("tts_voice", "tts_rate", "tts_pitch", "tts_vol"))
        if cfg == getattr(self, "_cfg", None):
            return
        self._cfg = cfg
        for v in self.e.availableVoices():
            if v.name() == st["tts_voice"]:
                self.e.setVoice(v); break
        self.e.setRate(float(st["tts_rate"]))
        self.e.setPitch(float(st["tts_pitch"]))
        self.e.setVolume(float(st["tts_vol"]))

    def say(self, t):
        if self.e and t.strip():
            self.e.say(t)

    def stop(self):
        if self.e:
            self.e.stop()

    def pause(self):
        if self.e:
            self.e.pause()

    def resume(self):
        if self.e:
            self.e.resume()

    def speaking(self):
        if not self.e:
            return False
        return "Speaking" in str(self.e.state())


class Update:
    """Проверка релиза через GitHub Releases API (только stdlib)."""
    def __init__(self, url):
        self.url = (url or "").rstrip("/")

    def check(self):
        import json
        req = urllib.request.Request(
            self.url, headers={"User-Agent": "LightRead/1.1", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        return dict(version=data.get("tag_name", ""),
                    url=data.get("html_url", ""),
                    notes=(data.get("body") or "")[:1200])


class WebDav:
    """Минимальный WebDAV-клиент на stdlib для синхронизации состояния чтения."""
    def __init__(self, url, user="", password=""):
        self.url = (url or "").rstrip("/")
        auth = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        self.auth = "Basic " + auth

    def _req(self, method, name="", data=None):
        req = urllib.request.Request(self.url + "/" + name, data=data, method=method)
        req.add_header("Authorization", self.auth)
        req.add_header("User-Agent", "LightRead/1.1")
        with urllib.request.urlopen(req, timeout=25) as response:
            return response.read()

    def ensure(self):
        try:
            self._req("MKCOL")
        except Exception:
            pass

    def put(self, name, data):
        self._req("PUT", name, data)

    def get(self, name):
        return self._req("GET", name)


class Sync:
    """Снимок прогресса, закладок и заметок, привязанный к путям книг."""
    NAME = "lightread.json"

    @staticmethod
    def export(lib):
        books = []
        for b in lib.q("SELECT path,progress,chapter,pos,pages,status,favorite,rsettings,seconds FROM books"):
            books.append({k: b[k] for k in b.keys()})
        marks, notes = [], []
        for m in lib.q("SELECT b.path,m.chapter,m.pos,m.title,m.text FROM marks m "
                       "JOIN books b ON b.id=m.book"):
            marks.append({k: m[k] for k in m.keys()})
        for n in lib.q("SELECT b.path,n.chapter,n.start,n.end,n.color,n.text,n.note,n.anchor "
                       "FROM notes n JOIN books b ON b.id=n.book"):
            notes.append({k: n[k] for k in n.keys()})
        return dict(version=1, books=books, marks=marks, notes=notes)

    @staticmethod
    def apply(lib, data):
        for b in data.get("books", []):
            row = lib.by_path(b.get("path", ""))
            if not row:
                continue
            lib.set_progress(row["id"], b.get("chapter", 0), b.get("pos", 0),
                             b.get("progress", 0), b.get("pages", 0))
            lib.set_field(row["id"], status=b.get("status", "new"),
                          favorite=b.get("favorite", 0),
                          rsettings=b.get("rsettings", ""), seconds=b.get("seconds", 0))
        for m in data.get("marks", []):
            row = lib.by_path(m.get("path", ""))
            if not row:
                continue
            lib.x("DELETE FROM marks WHERE book=? AND chapter=? AND pos=?",
                  (row["id"], m.get("chapter", 0), m.get("pos", 0)))
            lib.mark_add(row["id"], m.get("chapter", 0), m.get("pos", 0),
                         m.get("title", ""), m.get("text", ""))
        for n in data.get("notes", []):
            row = lib.by_path(n.get("path", ""))
            if not row:
                continue
            lib.x("DELETE FROM notes WHERE book=? AND chapter=? AND start=?",
                  (row["id"], n.get("chapter", 0), n.get("start", 0)))
            lib.note_add(row["id"], n.get("chapter", 0), n.get("start", 0), n.get("end", 0),
                         n.get("color", "#ffc94a"), n.get("text", ""), n.get("note", ""),
                         anchor=n.get("anchor", ""))


class Opds:
    """Минимальный OPDS-клиент на stdlib: Atom-фид и скачивание книг."""
    NS = "{http://www.w3.org/2005/Atom}"

    def __init__(self, url):
        self.url = url

    def _get(self, url):
        req = urllib.request.Request(url, headers={
            "User-Agent": "LightRead/1.1",
            "Accept": "application/atom+xml,application/xml,text/xml,*/*"})
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read()

    def feed(self, url=None):
        root = ET.fromstring(self._get(url or self.url))
        entries = []
        for el in root.findall(self.NS + "entry"):
            links = {}
            for link in el.findall(self.NS + "link"):
                links[link.get("rel", "alternate")] = link.get("href", "")
            author_el = el.find(self.NS + "author")
            author = (author_el.findtext(self.NS + "name") or "") if author_el is not None else ""
            entries.append(dict(title=(el.findtext(self.NS + "title") or "").strip(),
                                author=author.strip(), links=links,
                                ident=el.findtext(self.NS + "id") or ""))
        nxt = ""
        for link in root.findall(self.NS + "link"):
            if link.get("rel") == "next":
                nxt = link.get("href", "")
                break
        return entries, nxt

    def download(self, url, dest):
        data = self._get(url)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(data)
        return dest


class StarDict:
    """Чтение словарей StarDict (.ifo/.idx[.dz]/.dict[.dz])."""
    def __init__(self, paths):
        self.dicts = []
        for p in paths:
            root = Path(p)
            if root.is_file() and root.suffix == ".ifo":
                self._add(root)
            elif root.is_dir():
                for f in root.rglob("*.ifo"):
                    self._add(f)

    def _add(self, ifo):
        info = {}
        for line in ifo.read_text("utf-8", "replace").splitlines():
            if "=" in line:
                k, v = line.split("=", 1); info[k.strip()] = v.strip()
        base = ifo.with_suffix("")
        idx = base.with_suffix(".idx")
        dz = Path(str(idx) + ".dz")
        dfile = base.with_suffix(".dict")
        ddz = Path(str(dfile) + ".dz")
        self.dicts.append(dict(name=info.get("bookname", ifo.stem), info=info,
                               idx=idx if idx.exists() else (dz if dz.exists() else None),
                               dic=dfile if dfile.exists() else (ddz if ddz.exists() else None),
                               index=None))

    def _index(self, d):
        if d["index"] is not None:
            return d["index"]
        raw = d["idx"].read_bytes()
        if d["idx"].suffix == ".dz":
            raw = gzip.decompress(raw)
        wide = d["info"].get("idxoffsetbits") == "64"
        fmt = ">QI" if wide else ">II"
        size = struct.calcsize(fmt)
        idx, i = {}, 0
        while i < len(raw):
            z = raw.find(b"\0", i)
            if z < 0 or z + 1 + size > len(raw):
                break
            word = raw[i:z].decode("utf-8", "replace")
            off, ln = struct.unpack_from(fmt, raw, z + 1)
            idx.setdefault(word.lower(), (off, ln))
            i = z + 1 + size
        d["index"] = idx
        return idx

    def lookup(self, word):
        word = word.strip().lower().replace("ё", "е")
        out = []
        for d in self.dicts:
            if not d["idx"] or not d["dic"]:
                continue
            try:
                ent = self._index(d).get(word)
                if not ent:
                    ent = self._index(d).get(word.replace("е", "ё"))
                if not ent:
                    continue
                off, ln = ent
                if str(d["dic"]).endswith(".dz"):
                    with gzip.GzipFile(str(d["dic"])) as f:
                        f.seek(off); data = f.read(ln)
                else:
                    with open(d["dic"], "rb") as f:
                        f.seek(off); data = f.read(ln)
                txt = data.decode("utf-8", "replace")
                seq = d["info"].get("sametypesequence", "m")
                if seq.startswith("x"):
                    txt = re.sub(r"<k>(.*?)</k>", r"<b>\1</b>", txt)
                    txt = re.sub(r"<tr>(.*?)</tr>", r"[\1]", txt)
                    txt = re.sub(r"<ex>(.*?)</ex>", r"<i>\1</i>", txt)
                    txt = txt.replace("\n", "<br>")
                elif seq.startswith("h"):
                    pass
                else:
                    txt = "<pre style='white-space:pre-wrap'>" + txt.replace("\0", "\n") + "</pre>"
                out.append((d["name"], txt))
            except Exception:
                continue
        return out