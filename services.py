"""TTS (Qt TextToSpeech) и офлайн-словарь StarDict."""
import gzip, re, struct
from pathlib import Path
from PySide6.QtCore import QObject, Signal


class Tts(QObject):
    stateChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.e = None
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