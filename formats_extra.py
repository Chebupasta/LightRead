"""Поиск внешних помощников и распаковка/конвертация для «тяжёлых» форматов."""
import hashlib, os, re, shutil, subprocess, sys, tempfile, threading, zipfile
from pathlib import Path

import legacy_office

IS_WIN = os.name == "nt"
OLE_MAGIC = legacy_office.OLE_MAGIC
_PS_LOCK = threading.Lock()


def _native(path):
    """Office COM не открывает пути с прямыми слэшами, а библиотека хранит именно их."""
    return os.path.normpath(str(path)) if IS_WIN else str(path)


def _valid_zip(path, marker=None):
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        if marker:
            return marker in names
        return any(n in names for n in ("[Content_Types].xml", "word/document.xml",
                                        "ppt/presentation.xml", "content.xml"))
    except Exception:
        return False


def _valid_pdf(path):
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def _unlink(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def _first(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _pf(*rel):
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.environ.get("LOCALAPPDATA", "")]
    for r in roots:
        if not r:
            continue
        for x in rel:
            p = Path(r) / x
            if p.is_file():
                return str(p)
    return None


def seven_zip():
    return _first("7z", "7za", "7zr") or _pf(r"7-Zip\7z.exe", r"7-Zip\7za.exe")


def hh_exe():
    if not IS_WIN:
        return None
    p = Path(os.environ.get("WINDIR", r"C:\Windows")) / "hh.exe"
    return str(p) if p.is_file() else None


def soffice_exe():
    return _first("soffice", "soffice.exe", "libreoffice") or \
        _pf(r"LibreOffice\program\soffice.exe", r"OpenOffice\program\soffice.exe")


def antiword_exe():
    return _first("antiword", "catdoc")


def ddjvu_exe():
    return _first("ddjvu") or _pf(r"DjVuLibre\ddjvu.exe")


def has_mobi():
    try:
        import importlib.util
        return importlib.util.find_spec("mobi") is not None
    except Exception:
        return False


def word_exe():
    if not IS_WIN:
        return None
    return _first("WINWORD.EXE", "winword.exe") or _pf(
        r"Microsoft Office\root\Office16\WINWORD.EXE",
        r"Microsoft Office\Office16\WINWORD.EXE",
        r"Microsoft Office\root\Office15\WINWORD.EXE",
        r"Microsoft Office\Office15\WINWORD.EXE")


def powerpoint_exe():
    if not IS_WIN:
        return None
    return _first("POWERPNT.EXE", "powerpnt.exe") or _pf(
        r"Microsoft Office\root\Office16\POWERPNT.EXE",
        r"Microsoft Office\Office16\POWERPNT.EXE",
        r"Microsoft Office\root\Office15\POWERPNT.EXE",
        r"Microsoft Office\Office15\POWERPNT.EXE")


def has_word():
    if not IS_WIN:
        return False
    try:
        import importlib.util
        return importlib.util.find_spec("win32com") is not None or bool(word_exe())
    except Exception:
        return bool(word_exe())


def _com_candidate(path):
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False
    return head == OLE_MAGIC or head[:2] == b"PK" or Path(path).suffix.lower() == ".rtf"


_WORD_PS = """param([string]$src,[string]$dst,[int]$fmt)
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Word.Application
$app.Visible = $false
$app.DisplayAlerts = 0
try {
    $doc = $app.Documents.Open($src, $false, $true)
    $doc.SaveAs2($dst, $fmt)
    $doc.Close($false)
} finally {
    try { $app.Quit() } catch {}
}
"""

_PPT_PS = """param([string]$src,[string]$dst,[int]$fmt)
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
try {
    try { $pres = $app.Presentations.Open($src, $true, $false, $false) }
    catch { $pres = $app.Presentations.Open($src, $true, $false, $true) }
    $pres.SaveAs($dst, $fmt)
    $pres.Close()
} finally {
    try { $app.Quit() } catch {}
}
"""


def _ps_run(script, args, timeout=240):
    ps = _first("powershell", "pwsh")
    if not ps:
        return False
    fd, name = tempfile.mkstemp(prefix="lightread_", suffix=".ps1")
    os.close(fd)
    tmp = Path(name)
    try:
        tmp.write_text(script, encoding="utf-8-sig")
        with _PS_LOCK:
            cmd = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(tmp)]
            cmd += [_native(a) if isinstance(a, (str, Path)) else str(a) for a in args]
            r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def extract_archive(path, dest):
    exe = seven_zip()
    if not exe:
        return False
    dest = Path(dest); dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([exe, "x", "-y", f"-o{dest}", str(path)],
                       capture_output=True, timeout=300)
    return r.returncode == 0 and any(dest.iterdir())


def decompile_chm(path, dest):
    dest = Path(dest); dest.mkdir(parents=True, exist_ok=True)
    hh = hh_exe()
    if hh:
        try:
            subprocess.run([hh, "-decompile", str(dest), str(path)],
                           capture_output=True, timeout=180)
        except Exception:
            pass
        if any(dest.rglob("*.htm*")):
            return True
    return extract_archive(path, dest)


def _word_convert(path, out):
    try:
        import win32com.client as wc
    except Exception:
        return None
    app = None
    try:
        app = wc.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0
        doc = app.Documents.Open(_native(Path(path).resolve()), ReadOnly=True)
        doc.SaveAs2(_native(out), FileFormat=16)
        doc.Close(False)
        if Path(out).is_file() and _valid_zip(out, "word/document.xml"):
            return str(out)
        _unlink(out)
        return None
    except Exception:
        _unlink(out)
        return None
    finally:
        try:
            if app:
                app.Quit()
        except Exception:
            pass


def office_to_docx(path, outdir):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (Path(path).stem + ".docx")
    if out.is_file():
        if _valid_zip(out, "word/document.xml"):
            return str(out)
        _unlink(out)
    exe = soffice_exe()
    if exe:
        try:
            subprocess.run([exe, "--headless", "--norestore", "--convert-to", "docx",
                            "--outdir", str(outdir), _native(path)],
                           capture_output=True, timeout=240)
        except Exception:
            pass
        if out.is_file() and _valid_zip(out, "word/document.xml"):
            return str(out)
        _unlink(out)
    if word_exe() and _com_candidate(path):
        _ps_run(_WORD_PS, [path, out, 16])
        if out.is_file() and _valid_zip(out, "word/document.xml"):
            return str(out)
        _unlink(out)
    return _word_convert(path, out)


def _word_convert_pdf(path, out):
    try:
        import win32com.client as wc
    except Exception:
        return None
    app = None
    try:
        app = wc.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0
        doc = app.Documents.Open(_native(Path(path).resolve()), ReadOnly=True)
        doc.ExportAsFixedFormat(_native(out), 17)
        doc.Close(False)
        if Path(out).is_file() and _valid_pdf(out):
            return str(out)
        _unlink(out)
        return None
    except Exception:
        _unlink(out)
        return None
    finally:
        try:
            if app:
                app.Quit()
        except Exception:
            pass


def office_to_pdf(path, outdir):
    """Настоящий PDF из офисного документа — для точной обложки по первой странице."""
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (Path(path).stem + ".pdf")
    if out.is_file():
        if _valid_pdf(out):
            return str(out)
        _unlink(out)
    exe = soffice_exe()
    if exe:
        try:
            subprocess.run([exe, "--headless", "--norestore", "--convert-to", "pdf",
                            "--outdir", str(outdir), _native(path)],
                           capture_output=True, timeout=240)
        except Exception:
            pass
        if out.is_file() and _valid_pdf(out):
            return str(out)
        _unlink(out)
    ext = Path(path).suffix.lower()
    if ext in (".ppt", ".pps", ".pptx", ".ppsx", ".potx", ".odp", ".otp"):
        if powerpoint_exe() and _com_candidate(path):
            _ps_run(_PPT_PS, [path, out, 32])
            if out.is_file() and _valid_pdf(out):
                return str(out)
            _unlink(out)
    if word_exe() and _com_candidate(path):
        _ps_run(_WORD_PS, [path, out, 17])
        if out.is_file() and _valid_pdf(out):
            return str(out)
        _unlink(out)
    return _word_convert_pdf(path, out)


def _faithful_pdf(path):
    try:
        st = Path(path).stat()
    except OSError:
        return None, None
    from common import CACHE
    key = hashlib.md5(f"{path}|{st.st_mtime}|{st.st_size}".encode()).hexdigest()[:16]
    out = Path(CACHE) / "exact" / key
    return out, out / (Path(path).stem + ".pdf")


def office_faithful_cached(path):
    """Уже готовый PDF точного вида (без конвертации) или пустая строка."""
    _, pdf = _faithful_pdf(path)
    if pdf is not None and pdf.is_file() and _valid_pdf(pdf):
        return str(pdf)
    return ""


def office_faithful_pdf(path):
    """PDF с точной вёрсткой Office-документа: отдельный кэш по пути и времени файла."""
    out, pdf = _faithful_pdf(path)
    if out is None:
        return None
    if pdf.is_file() and _valid_pdf(pdf):
        return str(pdf)
    out.mkdir(parents=True, exist_ok=True)
    result = office_to_pdf(path, out)
    return result if result and _valid_pdf(result) else None


def office_to_pptx(path, outdir):
    """Конвертация legacy .ppt/.pps в PPTX через LibreOffice или PowerPoint."""
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (Path(path).stem + ".pptx")
    if out.is_file():
        if _valid_zip(out, "ppt/presentation.xml"):
            return str(out)
        _unlink(out)
    exe = soffice_exe()
    if exe:
        try:
            subprocess.run([exe, "--headless", "--norestore", "--convert-to", "pptx",
                            "--outdir", str(outdir), _native(path)],
                           capture_output=True, timeout=240)
        except Exception:
            pass
        if out.is_file() and _valid_zip(out, "ppt/presentation.xml"):
            return str(out)
        _unlink(out)
    if powerpoint_exe() and _com_candidate(path):
        _ps_run(_PPT_PS, [path, out, 24])
        if out.is_file() and _valid_zip(out, "ppt/presentation.xml"):
            return str(out)
        _unlink(out)
    return None


def office_to_text(path):
    exe = antiword_exe()
    if exe:
        args = [exe, "-w", "0", _native(path)] if "antiword" in Path(exe).name.lower() else [exe, _native(path)]
        try:
            r = subprocess.run(args, capture_output=True, timeout=120)
            if r.stdout:
                return r.stdout.decode("utf-8", "replace")
        except Exception:
            pass
    so = soffice_exe()
    if so:
        from common import CACHE
        out = Path(CACHE) / ("txt_" + re.sub(r"\W", "_", Path(path).stem)[:40])
        out.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run([so, "--headless", "--norestore", "--convert-to", "txt:Text",
                            "--outdir", str(out), _native(path)], capture_output=True, timeout=240)
            f = out / (Path(path).stem + ".txt")
            if f.is_file():
                return f.read_text("utf-8", "replace")
        except Exception:
            pass
    return None


EXTRA_EXTS = {".cbr", ".cb7", ".cbt", ".fb3", ".docm", ".dotx", ".ott", ".pdb", ".rar",
              ".pptx", ".ppt", ".pps", ".ppsx", ".potx", ".odp", ".otp"}


def legacy_ppt_slides(path):
    """Слайды legacy PPT: список списков строк."""
    try:
        return legacy_office.ppt_slides(path)
    except Exception:
        return []


def legacy_doc_text(path):
    try:
        return legacy_office.doc_text(path)
    except Exception:
        return ""


def _bad_ratio(text):
    if not text:
        return 1.0
    bad = 0
    for ch in text:
        code = ord(ch)
        if 0xE000 <= code <= 0xF8FF or 0xD800 <= code <= 0xDFFF:
            bad += 1
    return bad / len(text)


def _scrape(path):
    data = Path(path).read_bytes()
    best, best_score = [], 0
    for enc in ("utf-16le", "cp1251", "cp1252"):
        try:
            text = data.decode(enc, "ignore")
        except Exception:
            continue
        chunks = []
        for m in re.finditer(r"[^\x00-\x1f\x7f]{4,}", text):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            letters = sum(ch.isalpha() for ch in s)
            if letters < max(2, len(s) // 4):
                continue
            if _bad_ratio(s) > 0.15:
                continue
            if s.lower().startswith(("microsoft", "ms word", "powerpoint", "ole10native")):
                continue
            chunks.append(s)
        score = sum(len(x) for x in chunks)
        if score > best_score:
            best, best_score = chunks, score
    out, seen = [], set()
    for s in best:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return "\n".join(out)[:2_000_000]


def legacy_office_text(path):
    """Текст из бинарных DOC/PPT без внешних программ."""
    ext = Path(path).suffix.lower()
    if ext in (".ppt", ".pps"):
        slides = legacy_ppt_slides(path)
        if slides:
            return "\n\n".join("\n".join(lines) for lines in slides)
    elif ext in (".doc", ".dot"):
        text = legacy_doc_text(path)
        if text.strip():
            return text
    return _scrape(path)


def report():
    sz, hh, so, aw, dj = seven_zip(), hh_exe(), soffice_exe(), antiword_exe(), ddjvu_exe()
    rows = [
        ("EPUB 2/3", True, "встроенный парсер"),
        ("FB2 / FB2.ZIP", True, "встроенный парсер"),
        ("FB3", True, "встроенный парсер"),
        ("TXT / MD / HTML / XHTML", True, "встроенный парсер"),
        ("DOCX / DOCM / ODT / OTT", True, "встроенный парсер"),
        ("RTF", True, "встроенный парсер"),
        ("PDF", True, "QtPdf"),
        ("MOBI / PRC / PDB / AZW (PalmDOC)", True, "встроенный парсер"),
        ("CBZ", True, "встроенный парсер"),
        ("ZIP с TXT/HTML/FB2/EPUB", True, "встроенный парсер"),
        ("AZW3 (HUFF/CDIC)", has_mobi(), "pip install mobi"),
        ("CHM", bool(hh or sz), "Windows: hh.exe встроен" if hh else "нужен 7-Zip"),
        ("DOC (legacy)", bool(so or aw or has_word()),
         "Word / LibreOffice / antiword"),
        ("PPTX / POTX / PPSX", True, "встроенный парсер"),
        ("ODP / OTP", True, "встроенный парсер"),
        ("PPT / PPS (legacy)", bool(so or powerpoint_exe()),
         "PowerPoint / LibreOffice"),
        ("DJVU", bool(dj), "нужен DjVuLibre (ddjvu)"),
        ("CBR / CB7 / CBT", bool(sz), "нужен 7-Zip"),
    ]
    return rows, dict(seven=sz, hh=hh, soffice=so, antiword=aw, ddjvu=dj)