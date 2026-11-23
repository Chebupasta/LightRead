"""Текст из бинарных DOC/PPT (OLE-контейнер) без внешних зависимостей."""
import re
import struct
from pathlib import Path

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT = 0xFFFFFFFF


class Cfb:
    """Минимальное чтение Compound File Binary: заголовок, FAT, каталог, потоки."""

    def __init__(self, data):
        if not data.startswith(OLE_MAGIC):
            raise ValueError("not an OLE container")
        self.data = data
        self.ss = 1 << struct.unpack_from("<H", data, 0x1E)[0]
        self.mss = 1 << struct.unpack_from("<H", data, 0x20)[0]
        self.dir_start = struct.unpack_from("<I", data, 0x30)[0]
        self.mini_cutoff = struct.unpack_from("<I", data, 0x38)[0]
        self.minifat_start = struct.unpack_from("<I", data, 0x3C)[0]
        self.difat_start = struct.unpack_from("<I", data, 0x44)[0]
        self.num_difat = struct.unpack_from("<I", data, 0x48)[0]
        self._fat = self._read_fat()
        self._minifat = self._read_minifat()
        self.entries = self._read_dir()
        self._mini_stream = None

    def _sector(self, sid):
        off = (sid + 1) * self.ss
        return self.data[off:off + self.ss]

    def _read_fat(self):
        difat = list(struct.unpack_from("<109I", self.data, 0x4C))
        sid = self.difat_start
        per = self.ss // 4 - 1
        guard = 0
        while sid not in (_ENDOFCHAIN, _FREESECT) and guard < self.num_difat + 8:
            sec = self._sector(sid)
            if len(sec) < self.ss:
                break
            vals = list(struct.unpack_from("<" + "I" * (self.ss // 4), sec, 0))
            difat.extend(vals[:per])
            sid = vals[per]
            guard += 1
        fat = []
        for fsid in difat:
            if fsid in (_ENDOFCHAIN, _FREESECT):
                continue
            sec = self._sector(fsid)
            if len(sec) < self.ss:
                break
            fat.extend(struct.unpack_from("<" + "I" * (self.ss // 4), sec, 0))
        return fat

    def _read_minifat(self):
        if self.minifat_start in (_ENDOFCHAIN, _FREESECT):
            return []
        raw = self._chain(self.minifat_start)
        return list(struct.unpack_from("<" + "I" * (len(raw) // 4), raw, 0))

    def _chain(self, start):
        out = bytearray()
        sid = start
        seen = set()
        while sid not in (_ENDOFCHAIN, _FREESECT) and sid < len(self._fat) and sid not in seen:
            seen.add(sid)
            out += self._sector(sid)
            sid = self._fat[sid]
        return bytes(out)

    def _read_dir(self):
        raw = self._chain(self.dir_start)
        entries = []
        for off in range(0, len(raw) - 127, 128):
            name_len = struct.unpack_from("<H", raw, off + 0x40)[0]
            typ = raw[off + 0x42]
            if typ == 0 or name_len < 2 or name_len > 64:
                continue
            name = raw[off:off + name_len - 2].decode("utf-16le", "ignore")
            start = struct.unpack_from("<I", raw, off + 0x74)[0]
            size = struct.unpack_from("<Q", raw, off + 0x78)[0]
            if self.ss == 512:
                size &= 0xFFFFFFFF
            entries.append({"name": name, "type": typ, "start": start, "size": size})
        return entries

    def stream(self, name):
        want = name.lower()
        for e in self.entries:
            if e["type"] == 2 and e["name"].lower() == want:
                return self._read_entry(e)
        return b""

    def _read_entry(self, e):
        if not e["size"]:
            return b""
        if e["size"] < self.mini_cutoff:
            return self._read_mini(e["start"], e["size"])
        return self._chain(e["start"])[:e["size"]]

    def _mini_data(self):
        if self._mini_stream is None:
            root = next((x for x in self.entries if x["type"] == 5), None)
            self._mini_stream = self._chain(root["start"]) if root else b""
        return self._mini_stream

    def _read_mini(self, start, size):
        data = self._mini_data()
        out = bytearray()
        sid = start
        seen = set()
        while sid not in (_ENDOFCHAIN, _FREESECT) and sid < len(self._minifat) and sid not in seen:
            seen.add(sid)
            off = sid * self.mss
            out += data[off:off + self.mss]
            sid = self._minifat[sid]
        return bytes(out[:size])


def _records(buf):
    i, n = 0, len(buf)
    while i + 8 <= n:
        ver_inst, rtype, rlen = struct.unpack_from("<HHI", buf, i)
        i += 8
        if i + rlen > n:
            break
        yield ver_inst & 0xF, ver_inst >> 4, rtype, buf[i:i + rlen]
        i += rlen


def _cyr(text):
    return sum(1 for ch in text if "\u0400" <= ch <= "\u04FF")


def _ansi(text):
    best = text.decode("cp1252", "replace")
    for enc in ("cp1251", "cp866"):
        try:
            cur = text.decode(enc)
        except UnicodeDecodeError:
            continue
        if _cyr(cur) > _cyr(best):
            best = cur
    return best


def _ppt_atoms(buf, out):
    for ver, _inst, rtype, body in _records(buf):
        if rtype == 0x0FA0:
            out.append(body.decode("utf-16le", "ignore"))
        elif rtype == 0x0FA8:
            out.append(_ansi(body))
        elif rtype == 0x0FBA:
            out.append(body.decode("utf-16le", "ignore").rstrip("\x00"))
        elif ver == 0xF:
            _ppt_atoms(body, out)


def _slide_lines(atoms):
    lines = []
    for chunk in atoms:
        for line in chunk.replace("\x0b", "\r").split("\r"):
            line = re.sub(r"[\x00-\x08\x0e-\x1f]", "", line).strip()
            if not line or line.startswith("___PPT") or line in ("*", "•", "-", "–"):
                continue
            lines.append(line)
    return lines


def ppt_slides(path):
    """Список слайдов: каждый — список непустых строк."""
    data = Path(path).read_bytes()
    if not data.startswith(OLE_MAGIC):
        return []
    try:
        stream = Cfb(data).stream("PowerPoint Document")
    except Exception:
        return []
    if not stream:
        return []

    slides = []
    for ver, _inst, rtype, body in _records(stream):
        if rtype == 0x03EE and ver == 0xF:
            atoms = []
            _ppt_atoms(body, atoms)
            lines = _slide_lines(atoms)
            if lines:
                slides.append(lines)
    if slides:
        return slides

    for ver, inst, rtype, body in _records(stream):
        if rtype != 0x0FF0 or inst != 0:
            continue
        cur = None
        for _v, _i, t2, b2 in _records(body):
            if t2 == 0x03F3:
                cur = []
                slides.append(cur)
            elif cur is not None:
                _ppt_atoms(b2, cur)
    return [lines for lines in (_slide_lines(x) for x in slides) if lines]


def _find_pcdt(clx):
    i = 0
    while i < len(clx):
        kind = clx[i]
        if kind == 0x01:
            if i + 3 > len(clx):
                break
            cb = struct.unpack_from("<H", clx, i + 1)[0]
            i += 3 + cb
        elif kind == 0x02:
            if i + 5 > len(clx):
                break
            lcb = struct.unpack_from("<I", clx, i + 1)[0]
            return clx[i + 5:i + 5 + lcb]
        else:
            break
    return b""


def _piece_text(wd, pcdt):
    if len(pcdt) < 16:
        return ""
    n = (len(pcdt) - 4) // 12
    if n <= 0:
        return ""
    cps = struct.unpack_from("<" + "I" * (n + 1), pcdt, 0)
    base = 4 * (n + 1)
    out = []
    for k in range(n):
        off = base + k * 8
        if off + 8 > len(pcdt):
            break
        fc_raw = struct.unpack_from("<I", pcdt, off + 2)[0]
        ln = cps[k + 1] - cps[k]
        if ln <= 0:
            continue
        if fc_raw & 0x40000000:
            fc = (fc_raw & 0x3FFFFFFF) // 2
            chunk = wd[fc:fc + ln]
            out.append(_ansi(chunk))
        else:
            fc = fc_raw & 0x3FFFFFFF
            out.append(wd[fc:fc + ln * 2].decode("utf-16le", "replace"))
    return "".join(out)


def _clean_doc(text):
    out = []
    fields = 0
    for ch in text:
        if ch == "\x13":
            fields += 1
            continue
        if ch in ("\x14", "\x15"):
            fields = max(0, fields - 1)
            continue
        if fields:
            continue
        if ch in "\r\x0b":
            out.append("\n")
        elif ch == "\x0c":
            out.append("\n\n")
        elif ch == "\x07":
            out.append("\t")
        elif ch in "\x01\x02\x03\x04\x05\x06\x08\x1e\x1f":
            continue
        elif ch == "\t" or ch == "\n" or ord(ch) >= 0x20:
            out.append(ch)
    text = "".join(out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def doc_text(path):
    """Чистый текст Word 97+ через FIB и таблицу кусков (CLX)."""
    data = Path(path).read_bytes()
    if not data.startswith(OLE_MAGIC):
        return ""
    try:
        cfb = Cfb(data)
        wd = cfb.stream("WordDocument")
        if not wd or len(wd) < 0x01AA:
            return ""
        flags = struct.unpack_from("<H", wd, 0x0A)[0]
        table = cfb.stream("1Table" if flags & 0x0200 else "0Table")
        if not table:
            table = cfb.stream("1Table") or cfb.stream("0Table")
        if not table:
            return ""
        fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
        if not lcb_clx:
            return ""
        pcdt = _find_pcdt(table[fc_clx:fc_clx + lcb_clx])
        if not pcdt:
            return ""
        return _clean_doc(_piece_text(wd, pcdt))
    except Exception:
        return ""
