"""Поиск внешних помощников и распаковка/конвертация для «тяжёлых» форматов."""
import os, re, shutil, subprocess, sys
from pathlib import Path

IS_WIN = os.name == "nt"


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


def has_word():
    if not IS_WIN:
        return False
    try:
        import importlib.util
        return importlib.util.find_spec("win32com") is not None
    except Exception:
        return False


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
        doc = app.Documents.Open(str(Path(path).resolve()), ReadOnly=True)
        doc.SaveAs2(str(out), FileFormat=16)
        doc.Close(False)
        return str(out) if Path(out).is_file() else None
    except Exception:
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
        return str(out)
    exe = soffice_exe()
    if exe:
        try:
            subprocess.run([exe, "--headless", "--norestore", "--convert-to", "docx",
                            "--outdir", str(outdir), str(path)],
                           capture_output=True, timeout=240)
        except Exception:
            pass
        if out.is_file():
            return str(out)
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
        doc = app.Documents.Open(str(Path(path).resolve()), ReadOnly=True)
        doc.ExportAsFixedFormat(str(out), 17)
        doc.Close(False)
        return str(out) if Path(out).is_file() else None
    except Exception:
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
        return str(out)
    exe = soffice_exe()
    if exe:
        try:
            subprocess.run([exe, "--headless", "--norestore", "--convert-to", "pdf",
                            "--outdir", str(outdir), str(path)],
                           capture_output=True, timeout=240)
        except Exception:
            pass
        if out.is_file():
            return str(out)
    return _word_convert_pdf(path, out)


def office_to_pptx(path, outdir):
    """Конвертация legacy .ppt/.pps в PPTX через LibreOffice."""
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (Path(path).stem + ".pptx")
    if out.is_file():
        return str(out)
    exe = soffice_exe()
    if exe:
        try:
            subprocess.run([exe, "--headless", "--norestore", "--convert-to", "pptx",
                            "--outdir", str(outdir), str(path)],
                           capture_output=True, timeout=240)
        except Exception:
            pass
        if out.is_file():
            return str(out)
    return None


def office_to_text(path):
    exe = antiword_exe()
    if exe:
        args = [exe, "-w", "0", str(path)] if "antiword" in Path(exe).name.lower() else [exe, str(path)]
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
                            "--outdir", str(out), str(path)], capture_output=True, timeout=240)
            f = out / (Path(path).stem + ".txt")
            if f.is_file():
                return f.read_text("utf-8", "replace")
        except Exception:
            pass
    return None


EXTRA_EXTS = {".cbr", ".cb7", ".cbt", ".fb3", ".docm", ".dotx", ".ott", ".pdb", ".rar",
              ".pptx", ".ppt", ".pps", ".ppsx", ".potx", ".odp", ".otp"}


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
         "LibreOffice / Word / antiword"),
        ("PPTX / POTX / PPSX", True, "встроенный парсер"),
        ("ODP / OTP", True, "встроенный парсер"),
        ("PPT / PPS (legacy)", bool(so), "нужен LibreOffice"),
        ("DJVU", bool(dj), "нужен DjVuLibre (ddjvu)"),
        ("CBR / CB7 / CBT", bool(sz), "нужен 7-Zip"),
    ]
    return rows, dict(seven=sz, hh=hh, soffice=so, antiword=aw, ddjvu=dj)