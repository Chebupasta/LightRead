#!/usr/bin/env python3
"""LightRead — точка входа: single-instance, CLI, ассоциации файлов."""
import os, sys, hashlib
from pathlib import Path

os.environ.setdefault(
    "QT_LOGGING_RULES",
    "qt.qpa.fonts.warning=false;qt.text.font.db.warning=false;qt.multimedia.ffmpeg.info=false")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (QIcon, QPixmap, QPainter, QColor, QFont,
                           QLinearGradient, QPainterPath, QPen)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from common import APP, VER, DATA, S
from ui import Win


def make_icon():
    """Значок: раскрытая книга с закладкой на тёплом градиенте."""
    pm = QPixmap(64, 64); pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    g = QLinearGradient(0, 0, 64, 64)
    g.setColorAt(0.0, QColor("#f7b27c"))
    g.setColorAt(1.0, QColor("#d9662b"))
    p.setBrush(g)
    p.drawRoundedRect(3, 3, 58, 58, 14, 14)

    paper = QColor("#fffaf2")
    # левая страница
    left = QPainterPath()
    left.moveTo(11, 19)
    left.cubicTo(18, 15, 25, 15, 31, 20)
    left.lineTo(31, 47)
    left.cubicTo(25, 42, 18, 42, 11, 46)
    left.closeSubpath()
    # правая страница
    right = QPainterPath()
    right.moveTo(53, 19)
    right.cubicTo(46, 15, 37, 15, 33, 20)
    right.lineTo(33, 47)
    right.cubicTo(37, 42, 46, 42, 53, 46)
    right.closeSubpath()
    p.setBrush(paper)
    p.drawPath(left); p.drawPath(right)

    # линии текста
    p.setPen(QPen(QColor("#e2c9a8"), 1.4))
    for y, w in ((26, 13), (31, 15), (36, 11)):
        p.drawLine(15, y, 15 + w, y)
        p.drawLine(49 - w, y, 49, y)
    # закладка
    p.setPen(Qt.NoPen); p.setBrush(QColor("#c8501f"))
    book = QPainterPath()
    book.moveTo(37, 17); book.lineTo(44, 17); book.lineTo(44, 34)
    book.lineTo(40.5, 30.5); book.lineTo(37, 34); book.closeSubpath()
    p.drawPath(book)
    p.end()
    return QIcon(pm)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP); app.setApplicationVersion(VER)
    app.setOrganizationName(APP); app.setWindowIcon(make_icon())
    key = "lightread-" + hashlib.md5(str(DATA).encode()).hexdigest()[:12]
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(300):
        sock.write("\n".join(args).encode("utf-8")); sock.flush(); sock.waitForBytesWritten(500)
        return 0

    from formats_extra import cleanup_faithful_pdfs
    cleanup_faithful_pdfs()
    cache_timer = QTimer()
    cache_timer.timeout.connect(cleanup_faithful_pdfs)
    cache_timer.start(24 * 60 * 60 * 1000)

    win = Win()
    win.show()

    srv = QLocalServer()
    QLocalServer.removeServer(key)
    srv.listen(key)

    def on_conn():
        c = srv.nextPendingConnection()
        if not c:
            return
        c.waitForReadyRead(500)
        data = bytes(c.readAll()).decode("utf-8", "replace")
        opened = None
        for p in filter(None, data.split("\n")):
            if Path(p).is_file():
                before = len(win.readers)
                win.import_path(p, open_it=True)
                if len(win.readers) > before:
                    opened = win.readers[-1]
        target = opened or win
        target.raise_(); target.activateWindow()

    srv.newConnection.connect(on_conn)
    QTimer.singleShot(300, lambda: [win.import_path(p, open_it=True) for p in args if Path(p).is_file()])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())