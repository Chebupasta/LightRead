"""SQLite-хранилище библиотеки."""
import re, shutil, sqlite3, threading, time
from pathlib import Path
from common import DB, COVERS, S, PRESENTATION_FMTS, norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS books(
 id INTEGER PRIMARY KEY, path TEXT UNIQUE, fmt TEXT, title TEXT, author TEXT, series TEXT, seq REAL DEFAULT 0,
 lang TEXT, annotation TEXT, genres TEXT, size INTEGER, mtime REAL, added REAL,
 last_read REAL DEFAULT 0, progress REAL DEFAULT 0, status TEXT DEFAULT 'new', favorite INTEGER DEFAULT 0,
 chapter INTEGER DEFAULT 0, pos INTEGER DEFAULT 0, pages INTEGER DEFAULT 0,
 rsettings TEXT DEFAULT '', seconds REAL DEFAULT 0, manual_meta INTEGER DEFAULT 0,
 fhash TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS book_tag(tag INTEGER, book INTEGER, PRIMARY KEY(tag,book));
CREATE TABLE IF NOT EXISTS coll(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS coll_book(coll INTEGER, book INTEGER, PRIMARY KEY(coll,book));
CREATE TABLE IF NOT EXISTS marks(id INTEGER PRIMARY KEY, book INTEGER, chapter INTEGER, pos INTEGER,
 title TEXT, text TEXT, created REAL);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, book INTEGER, chapter INTEGER, start INTEGER,
 end INTEGER, color TEXT, text TEXT, note TEXT, created REAL, anchor TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS stats(day TEXT, book INTEGER, seconds REAL, pages INTEGER, PRIMARY KEY(day,book));
CREATE INDEX IF NOT EXISTS i_title ON books(title); CREATE INDEX IF NOT EXISTS i_read ON books(last_read);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text, note,
  content='notes', content_rowid='id', tokenize='unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS marks_fts USING fts5(title, text,
  content='marks', content_rowid='id', tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
  INSERT INTO notes_fts(rowid,text,note) VALUES(new.id,new.text,new.note); END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
  INSERT INTO notes_fts(notes_fts,rowid,text,note) VALUES('delete',old.id,old.text,old.note); END;
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
  INSERT INTO notes_fts(notes_fts,rowid,text,note) VALUES('delete',old.id,old.text,old.note);
  INSERT INTO notes_fts(rowid,text,note) VALUES(new.id,new.text,new.note); END;
CREATE TRIGGER IF NOT EXISTS marks_ai AFTER INSERT ON marks BEGIN
  INSERT INTO marks_fts(rowid,title,text) VALUES(new.id,new.title,new.text); END;
CREATE TRIGGER IF NOT EXISTS marks_ad AFTER DELETE ON marks BEGIN
  INSERT INTO marks_fts(marks_fts,rowid,title,text) VALUES('delete',old.id,old.title,old.text); END;
CREATE TRIGGER IF NOT EXISTS marks_au AFTER UPDATE ON marks BEGIN
  INSERT INTO marks_fts(marks_fts,rowid,title,text) VALUES('delete',old.id,old.title,old.text);
  INSERT INTO marks_fts(rowid,title,text) VALUES(new.id,new.title,new.text); END;
"""
ORDER = {"added_desc": "added DESC", "added_asc": "added ASC", "title": "title COLLATE NOCASE",
         "author": "author COLLATE NOCASE, title COLLATE NOCASE", "read": "last_read DESC",
         "progress": "progress DESC", "size": "size DESC", "fmt": "fmt, title COLLATE NOCASE",
         "series": "series COLLATE NOCASE, seq, title COLLATE NOCASE"}


class Library:
    def __init__(self, path=DB):
        self.lock = threading.RLock()
        self.path = Path(path)
        self.integrity_ok = True
        self.integrity_backup = ""
        self.fts_ok = False
        self.c = self._connect()
        with self.lock:
            usable = False
            try:
                result = self.c.execute("PRAGMA integrity_check").fetchone()[0]
                usable = result == "ok"
                if usable:
                    self._setup()
            except sqlite3.DatabaseError:
                usable = False
            if not usable:
                self.integrity_ok = False
                try:
                    self.c.close()
                except sqlite3.Error:
                    pass
                backup = self.path.with_name(self.path.name + f".corrupt-{int(time.time())}")
                try:
                    shutil.copy2(self.path, backup)
                    self.integrity_backup = str(backup)
                except OSError:
                    pass
                self.path.unlink(missing_ok=True)
                self.c = self._connect()
                self._setup()

    def _connect(self):
        c = sqlite3.connect(str(self.path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _setup(self):
        with self.lock:
            self.c.executescript(SCHEMA)
            cols = {r["name"] for r in self.c.execute("PRAGMA table_info(books)")}
            if "manual_meta" not in cols:
                self.c.execute("ALTER TABLE books ADD COLUMN manual_meta INTEGER DEFAULT 0")
            if "fhash" not in cols:
                self.c.execute("ALTER TABLE books ADD COLUMN fhash TEXT DEFAULT ''")
            ncols = {r["name"] for r in self.c.execute("PRAGMA table_info(notes)")}
            if "anchor" not in ncols:
                self.c.execute("ALTER TABLE notes ADD COLUMN anchor TEXT DEFAULT ''")
            self.c.commit()
            self._dedupe_paths()
            try:
                self.c.executescript(FTS_SCHEMA)
                self.c.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
                self.c.execute("INSERT INTO marks_fts(marks_fts) VALUES('rebuild')")
                self.c.commit()
                self.fts_ok = True
            except sqlite3.Error:
                self.fts_ok = False

    def _dedupe_paths(self):
        """Слить строки, которые указывают на один и тот же файл."""
        rows = self.q("SELECT id,path FROM books ORDER BY id")
        keepers = {}
        for r in rows:
            key = norm(r["path"])
            if key not in keepers:
                keepers[key] = r["id"]
                if key != r["path"]:
                    self.x("UPDATE books SET path=? WHERE id=?", (key, r["id"]))
                continue
            old, new = r["id"], keepers[key]
            for table in ("marks", "notes", "stats", "book_tag", "coll_book"):
                self.c.execute(f"UPDATE OR IGNORE {table} SET book=? WHERE book=?", (new, old))
            self.x("DELETE FROM books WHERE id=?", (old,))
            old_cover, new_cover = COVERS / f"{old}.png", COVERS / f"{new}.png"
            if new_cover.exists():
                try:
                    old_cover.unlink()
                except OSError:
                    pass

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
                self.x("UPDATE books SET fmt=?,size=?,mtime=?,fhash=? WHERE id=?",
                       (d["fmt"], d["size"], d["mtime"], d.get("fhash", ""), old[0]["id"]))
            else:
                self.x("UPDATE books SET fmt=?,title=?,author=?,series=?,seq=?,lang=?,annotation=?,genres=?,"
                       "size=?,mtime=?,fhash=? WHERE id=?",
                       (d["fmt"], d["title"], d["author"], d["series"], d["seq"], d["lang"], d["annotation"],
                        d["genres"], d["size"], d["mtime"], d.get("fhash", ""), old[0]["id"]))
            return old[0]["id"]
        return self.x("INSERT INTO books(path,fmt,title,author,series,seq,lang,annotation,genres,size,mtime,added,fhash)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (norm(d["path"]), d["fmt"], d["title"], d["author"], d["series"], d["seq"], d["lang"],
                       d["annotation"], d["genres"], d["size"], d["mtime"], time.time(), d.get("fhash", "")))

    def known(self):
        return {r["path"]: (r["size"], r["mtime"]) for r in self.q("SELECT path,size,mtime FROM books")}

    def book(self, bid):
        r = self.q("SELECT * FROM books WHERE id=?", (bid,))
        return r[0] if r else None

    def by_path(self, path):
        r = self.q("SELECT * FROM books WHERE path=?", (norm(path),))
        return r[0] if r else None

    def _smart_match(self, b, r):
        if r.get("status") and b["status"] != r["status"]:
            return False
        if r.get("fmt") and b["fmt"] != r["fmt"]:
            return False
        if r.get("favorite") and not b["favorite"]:
            return False
        if r.get("tag") and not self.q("SELECT 1 FROM book_tag WHERE tag=? AND book=?",
                                       (r["tag"], b["id"])):
            return False
        if r.get("days") and time.time() - (b["added"] or 0) > float(r["days"]) * 86400:
            return False
        if b["progress"] < float(r.get("min_progress", 0)):
            return False
        if b["progress"] > float(r.get("max_progress", 1)):
            return False
        return True

    def books(self, flt=None, search="", sort="added_desc"):
        w, a = [], []
        f = flt or {}
        k = f.get("kind")
        if k == "smart":
            rule = next((x for x in S.get("smart", []) if x.get("name") == f.get("value")), None)
            rows = [r for r in self.q("SELECT * FROM books")
                    if rule and self._smart_match(r, rule)]
            if search:
                q = f"%{search}%".lower()
                rows = [r for r in rows if any(q in str(r[c] or "").lower()
                                               for c in ("title", "author", "series", "annotation"))]
            return rows
        if k == "presentations":
            w.append("fmt IN (" + ",".join("?" for _ in PRESENTATION_FMTS) + ")")
            a.extend(PRESENTATION_FMTS)
        elif k == "status": w.append("status=?"); a.append(f["value"])
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
            like = f"%{search}%"
            parts = ["title LIKE ?", "author LIKE ?", "series LIKE ?", "annotation LIKE ?"]
            args = [like] * 4
            if self.fts_ok:
                terms = re.findall(r"\w+", search, re.UNICODE)
                match = " ".join(t + "*" for t in terms)
                if not match:
                    match = '"' + search.replace('"', '""') + '"'
                parts += ["id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?)",
                          "id IN (SELECT rowid FROM marks_fts WHERE marks_fts MATCH ?)"]
                args += [match, match]
            else:
                parts += ["id IN (SELECT book FROM notes WHERE note LIKE ? OR text LIKE ?)",
                          "id IN (SELECT book FROM marks WHERE title LIKE ? OR text LIKE ?)"]
                args += [like] * 4
            w.append("(" + " OR ".join(parts) + ")")
            a += args
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
    def note_add(self, bid, ch, s, e, color, text, note="", anchor=""):
        return self.x("INSERT INTO notes(book,chapter,start,end,color,text,note,created,anchor) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (bid, ch, s, e, color, text, note, time.time(), anchor))

    def hashes(self):
        return {r["fhash"]: r["path"] for r in self.q("SELECT fhash,path FROM books WHERE fhash!=''")}
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