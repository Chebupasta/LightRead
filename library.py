"""SQLite-хранилище библиотеки."""
import sqlite3, threading, time
from pathlib import Path
from common import DB, norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS books(
 id INTEGER PRIMARY KEY, path TEXT UNIQUE, fmt TEXT, title TEXT, author TEXT, series TEXT, seq REAL DEFAULT 0,
 lang TEXT, annotation TEXT, genres TEXT, size INTEGER, mtime REAL, added REAL,
 last_read REAL DEFAULT 0, progress REAL DEFAULT 0, status TEXT DEFAULT 'new', favorite INTEGER DEFAULT 0,
 chapter INTEGER DEFAULT 0, pos INTEGER DEFAULT 0, pages INTEGER DEFAULT 0,
 rsettings TEXT DEFAULT '', seconds REAL DEFAULT 0, manual_meta INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS book_tag(tag INTEGER, book INTEGER, PRIMARY KEY(tag,book));
CREATE TABLE IF NOT EXISTS coll(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS coll_book(coll INTEGER, book INTEGER, PRIMARY KEY(coll,book));
CREATE TABLE IF NOT EXISTS marks(id INTEGER PRIMARY KEY, book INTEGER, chapter INTEGER, pos INTEGER,
 title TEXT, text TEXT, created REAL);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, book INTEGER, chapter INTEGER, start INTEGER,
 end INTEGER, color TEXT, text TEXT, note TEXT, created REAL);
CREATE TABLE IF NOT EXISTS stats(day TEXT, book INTEGER, seconds REAL, pages INTEGER, PRIMARY KEY(day,book));
CREATE INDEX IF NOT EXISTS i_title ON books(title); CREATE INDEX IF NOT EXISTS i_read ON books(last_read);
"""
ORDER = {"added_desc": "added DESC", "added_asc": "added ASC", "title": "title COLLATE NOCASE",
         "author": "author COLLATE NOCASE, title COLLATE NOCASE", "read": "last_read DESC",
         "progress": "progress DESC", "size": "size DESC", "fmt": "fmt, title COLLATE NOCASE",
         "series": "series COLLATE NOCASE, seq, title COLLATE NOCASE"}


class Library:
    def __init__(self, path=DB):
        self.lock = threading.RLock()
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        with self.lock:
            self.c.executescript(SCHEMA)
            cols = {r["name"] for r in self.c.execute("PRAGMA table_info(books)")}
            if "manual_meta" not in cols:
                self.c.execute("ALTER TABLE books ADD COLUMN manual_meta INTEGER DEFAULT 0")
            self.c.commit()

    def q(self, sql, a=()):
        with self.lock:
            return self.c.execute(sql, a).fetchall()

    def x(self, sql, a=()):
        with self.lock:
            cur = self.c.execute(sql, a); self.c.commit()
            return cur.lastrowid

    # ── книги ──
    def upsert(self, d):
        old = self.q("SELECT id,size,mtime,manual_meta FROM books WHERE path=?", (norm(d["path"]),))
        if old:
            if old[0]["manual_meta"]:
                # метаданные, введённые вручную, сканер не перезаписывает
                self.x("UPDATE books SET fmt=?,size=?,mtime=? WHERE id=?",
                       (d["fmt"], d["size"], d["mtime"], old[0]["id"]))
            else:
                self.x("UPDATE books SET fmt=?,title=?,author=?,series=?,seq=?,lang=?,annotation=?,genres=?,"
                       "size=?,mtime=? WHERE id=?",
                       (d["fmt"], d["title"], d["author"], d["series"], d["seq"], d["lang"], d["annotation"],
                        d["genres"], d["size"], d["mtime"], old[0]["id"]))
            return old[0]["id"]
        return self.x("INSERT INTO books(path,fmt,title,author,series,seq,lang,annotation,genres,size,mtime,added)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (norm(d["path"]), d["fmt"], d["title"], d["author"], d["series"], d["seq"], d["lang"],
                       d["annotation"], d["genres"], d["size"], d["mtime"], time.time()))

    def known(self):
        return {r["path"]: (r["size"], r["mtime"]) for r in self.q("SELECT path,size,mtime FROM books")}

    def book(self, bid):
        r = self.q("SELECT * FROM books WHERE id=?", (bid,))
        return r[0] if r else None

    def by_path(self, path):
        r = self.q("SELECT * FROM books WHERE path=?", (norm(path),))
        return r[0] if r else None

    def books(self, flt=None, search="", sort="added_desc"):
        w, a = [], []
        f = flt or {}
        k = f.get("kind")
        if k == "status": w.append("status=?"); a.append(f["value"])
        elif k == "fav": w.append("favorite=1")
        elif k == "recent": w.append("last_read>0")
        elif k == "unread": w.append("progress<0.005")
        elif k == "author": w.append("author LIKE ?"); a.append(f"%{f['value']}%")
        elif k == "series": w.append("series=?"); a.append(f["value"])
        elif k == "fmt": w.append("fmt=?"); a.append(f["value"])
        elif k == "folder": w.append("path LIKE ?"); a.append(norm(f["value"]).rstrip("/") + "/%")
        elif k == "coll": w.append("id IN (SELECT book FROM coll_book WHERE coll=?)"); a.append(f["value"])
        elif k == "tag": w.append("id IN (SELECT book FROM book_tag WHERE tag=?)"); a.append(f["value"])
        if search:
            w.append("(title LIKE ? OR author LIKE ? OR series LIKE ?)"); a += [f"%{search}%"] * 3
        sql = "SELECT * FROM books" + (" WHERE " + " AND ".join(w) if w else "")
        if k == "recent":
            sql += " ORDER BY last_read DESC LIMIT 60"
        else:
            sql += " ORDER BY " + ORDER.get(sort, "added DESC")
        return self.q(sql, a)

    def set_progress(self, bid, ch, pos, prog, pages=0):
        b = self.book(bid)
        if not b:
            return
        status = "read" if prog >= 0.995 else ("reading" if prog > 0.001 or b["status"] == "reading" else b["status"])
        if b["status"] == "planned" and prog <= 0.001:
            status = "planned"
        self.x("UPDATE books SET chapter=?,pos=?,progress=?,pages=?,last_read=?,status=? WHERE id=?",
               (ch, pos, min(1.0, prog), pages, time.time(), status, bid))

    def set_field(self, bid, **kw):
        if kw:
            self.x(f"UPDATE books SET {','.join(k+'=?' for k in kw)} WHERE id=?", (*kw.values(), bid))

    def set_meta(self, bid, **kw):
        if kw:
            kw["manual_meta"] = 1
            self.set_field(bid, **kw)

    # ── метки ──
    def tags(self):
        return self.q("SELECT t.id,t.name,COUNT(b.book) n FROM tags t LEFT JOIN book_tag b ON b.tag=t.id "
                      "GROUP BY t.id ORDER BY t.name")

    def new_tag(self, name):
        row = self.q("SELECT id FROM tags WHERE name=?", (name,))
        return row[0]["id"] if row else self.x("INSERT INTO tags(name) VALUES(?)", (name,))

    def tag_drop(self, tid):
        self.x("DELETE FROM book_tag WHERE tag=?", (tid,)); self.x("DELETE FROM tags WHERE id=?", (tid,))

    def book_tags(self, bid):
        return [r["tag"] for r in self.q("SELECT tag FROM book_tag WHERE book=?", (bid,))]

    def tag_book(self, tid, bid, on):
        if on:
            self.x("INSERT OR IGNORE INTO book_tag(tag,book) VALUES(?,?)", (tid, bid))
        else:
            self.x("DELETE FROM book_tag WHERE tag=? AND book=?", (tid, bid))

    def remove(self, bid, delete_file=False):
        b = self.book(bid)
        if not b:
            return
        if delete_file:
            try:
                Path(b["path"]).unlink()
            except OSError:
                pass
        for t in ("marks", "notes", "stats", "coll_book"):
            col = "book"
            self.x(f"DELETE FROM {t} WHERE {col}=?", (bid,))
        self.x("DELETE FROM books WHERE id=?", (bid,))

    def distinct(self, field):
        return [r[0] for r in self.q(f"SELECT DISTINCT {field} FROM books WHERE {field}<>'' ORDER BY {field} COLLATE NOCASE")]

    def folders(self):
        return sorted({str(Path(r["path"]).parent) for r in self.q("SELECT path FROM books")})

    # ── коллекции ──
    def colls(self): return self.q("SELECT * FROM coll ORDER BY name COLLATE NOCASE")
    def new_coll(self, name):
        row = self.q("SELECT id FROM coll WHERE name=?", (name,))
        return row[0]["id"] if row else self.x("INSERT INTO coll(name) VALUES(?)", (name,))
    def coll_add(self, cid, bid): self.x("INSERT OR IGNORE INTO coll_book VALUES(?,?)", (cid, bid))
    def coll_del(self, cid, bid): self.x("DELETE FROM coll_book WHERE coll=? AND book=?", (cid, bid))
    def coll_drop(self, cid):
        self.x("DELETE FROM coll_book WHERE coll=?", (cid,)); self.x("DELETE FROM coll WHERE id=?", (cid,))
    def book_colls(self, bid): return [r["coll"] for r in self.q("SELECT coll FROM coll_book WHERE book=?", (bid,))]

    # ── закладки / заметки / статистика ──
    def marks(self, bid): return self.q("SELECT * FROM marks WHERE book=? ORDER BY chapter,pos", (bid,))
    def mark_add(self, bid, ch, pos, title, text):
        return self.x("INSERT INTO marks(book,chapter,pos,title,text,created) VALUES(?,?,?,?,?,?)",
                      (bid, ch, pos, title, text, time.time()))
    def mark_del(self, mid): self.x("DELETE FROM marks WHERE id=?", (mid,))
    def mark_upd(self, mid, **kw):
        if kw:
            self.x(f"UPDATE marks SET {','.join(k+'=?' for k in kw)} WHERE id=?", (*kw.values(), mid))

    def notes(self, bid): return self.q("SELECT * FROM notes WHERE book=? ORDER BY chapter,start", (bid,))
    def note_add(self, bid, ch, s, e, color, text, note=""):
        return self.x("INSERT INTO notes(book,chapter,start,end,color,text,note,created) VALUES(?,?,?,?,?,?,?,?)",
                      (bid, ch, s, e, color, text, note, time.time()))
    def note_upd(self, nid, **kw):
        if kw:
            self.x(f"UPDATE notes SET {','.join(k+'=?' for k in kw)} WHERE id=?", (*kw.values(), nid))
    def note_del(self, nid): self.x("DELETE FROM notes WHERE id=?", (nid,))

    def stats_add(self, bid, sec, pages):
        day = time.strftime("%Y-%m-%d")
        self.x("INSERT INTO stats(day,book,seconds,pages) VALUES(?,?,?,?) "
               "ON CONFLICT(day,book) DO UPDATE SET seconds=seconds+?, pages=pages+?",
               (day, bid, sec, pages, sec, pages))
        self.x("UPDATE books SET seconds=seconds+? WHERE id=?", (sec, bid))

    def stats(self): return self.q("SELECT day,SUM(seconds) s,SUM(pages) p FROM stats GROUP BY day ORDER BY day DESC LIMIT 90")