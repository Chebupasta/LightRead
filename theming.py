"""Единая тема: оформление приложения следует за темой чтения.

Дизайн-язык «Paper & Ink»: спокойные графитовые поверхности вокруг
бумажной страницы, тёплый акцент-маркер, мягкие скругления и тонкие
разделители вместо тяжёлых рамок.
"""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from common import THEMES, ACCENT, norm_theme

_last = None


def chrome(th):
    """Параметры оформления «обвязки»: белая или чёрная, без оттенков."""
    if th["dark"]:
        return dict(
            win="#000000", panel="#0d0d0d", field="#111111", border="#2a2a2a",
            text="#ffffff", dim="#aaaaaa", hover="#1c1c1c", sel="#1c3a5e",
            accent="#5b9cff", onaccent="#000000", accent2="#8ab4f8",
            track="#222222", thumb="#4a4a4a", divider="#242424",
            chip="#161616", shadow="#60000000", page=th["desk"],
        )
    return dict(
        win="#ffffff", panel="#f5f5f5", field="#ffffff", border="#d0d0d0",
        text="#000000", dim="#666666", hover="#ececec", sel="#d3e3fd",
        accent="#2f6fe0", onaccent="#ffffff", accent2="#0b57d0",
        track="#e8e8e8", thumb="#b8b8b8", divider="#e0e0e0",
        chip="#f1f1f1", shadow="#18000000", page=th["desk"],
    )


TPL = """
* { outline: 0; }

QWidget {
  background: %(win)s; color: %(text)s;
  font-family: "Segoe UI", "Inter", "Noto Sans", "Helvetica Neue", sans-serif;
  font-size: 13px;
}
QMainWindow, QDialog { background: %(win)s; }
QFrame { border-radius: 16px; }
QToolTip {
  background: %(field)s; color: %(text)s; border: 1px solid %(border)s;
  border-radius: 12px; padding: 9px 13px;
}

/* ── Меню ─────────────────────────────────────────────────────────── */
QMenuBar { background: %(panel)s; padding: 3px 8px; border-bottom: 1px solid %(divider)s;
  border-radius: 10px 10px 0 0; }
QMenuBar::item { padding: 6px 13px; border-radius: 7px; background: transparent; color: %(dim)s; }
QMenuBar::item:selected { background: %(hover)s; color: %(text)s; }
QMenu {
  background: %(field)s; border: 1px solid %(border)s; border-radius: 14px;
  padding: 8px;
}
QMenu::item { padding: 9px 26px 9px 14px; border-radius: 7px; color: %(text)s; }
QMenu::item:selected { background: %(accent)s; color: %(onaccent)s; }
QMenu::separator { height: 1px; background: %(divider)s; margin: 6px 10px; }

/* ── Панели инструментов ──────────────────────────────────────────── */
QToolBar {
  background: %(panel)s; border: 0; border-bottom: 1px solid %(divider)s;
  padding: 7px 12px; spacing: 4px;
}
QToolButton {
  background: transparent; color: %(text)s; padding: 8px 12px;
  border-radius: 10px; border: 1px solid transparent; font-size: 12.5px;
}
QToolButton:hover { background: %(hover)s; border-color: %(border)s; }
QToolButton:pressed { background: %(sel)s; }
QToolButton:checked { background: %(accent)s; color: %(onaccent)s; border-color: %(accent)s; font-weight: 600; }
QToolBar::separator { width: 1px; background: %(divider)s; margin: 5px 8px; }

/* ── Статус-бар ───────────────────────────────────────────────────── */
QStatusBar { background: %(panel)s; border-top: 1px solid %(divider)s; color: %(dim)s; }
QStatusBar QLabel { color: %(dim)s; padding: 0 8px; font-size: 12px; border-radius: 6px; }
QStatusBar::item { border: 0; }
QStatusBar QSpinBox { padding: 3px 5px; font-size: 11px; border-radius: 7px; }
QStatusBar QSlider { max-height: 18px; border-radius: 6px; }

/* ── Док-панель и вкладки ─────────────────────────────────────────── */
QDockWidget { color: %(dim)s; border-radius: 12px; }
QDockWidget::title {
  background: %(panel)s; padding: 9px 12px;
  border-bottom: 1px solid %(divider)s; border-radius: 10px 10px 0 0;
  font-size: 11px; font-weight: 600;
}
QTabWidget::pane { border: 0; background: %(win)s; top: -1px; border-radius: 12px; }
QTabBar::tab {
  background: transparent; color: %(dim)s; padding: 9px 14px;
  border-bottom: 2px solid transparent; margin: 0 2px;
  border-radius: 10px 10px 0 0;
}
QTabBar::tab:selected { color: %(text)s; border-bottom: 2px solid %(accent)s; background: %(panel)s; }
QTabBar::tab:hover:!selected { color: %(text)s; background: %(hover)s; }

/* ── Поля ввода ───────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextBrowser, QFontComboBox {
  background: %(field)s; border: 1px solid %(border)s; border-radius: 11px;
  padding: 8px 11px; color: %(text)s;
  selection-background-color: %(accent)s; selection-color: %(onaccent)s;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QTextBrowser:focus { border-color: %(accent)s; }
QComboBox::drop-down { border: 0; width: 22px; border-top-right-radius: 11px; border-bottom-right-radius: 11px; }
QComboBox QAbstractItemView {
  background: %(field)s; border: 1px solid %(border)s; border-radius: 10px;
  padding: 5px; selection-background-color: %(accent)s; selection-color: %(onaccent)s;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
  width: 16px; background: transparent; border: 0; border-radius: 5px;
}

/* ── Кнопки и переключатели ───────────────────────────────────────── */
QPushButton {
  background: %(hover)s; border: 1px solid %(border)s; border-radius: 12px;
  padding: 9px 16px; color: %(text)s;
}
QPushButton:hover { background: %(sel)s; border-color: %(accent)s; }
QPushButton:pressed { background: %(accent)s; color: %(onaccent)s; }
QPushButton:default { background: %(accent)s; color: %(onaccent)s; border-color: %(accent)s; font-weight: 600; }
QPushButton:flat { border: 0; background: transparent; }
QCheckBox, QRadioButton { spacing: 10px; }
QCheckBox::indicator, QRadioButton::indicator {
  width: 18px; height: 18px; border-radius: 7px;
  border: 1px solid %(border)s; background: %(field)s;
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: %(accent)s; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
  background: %(accent)s; border-color: %(accent)s;
}
QRadioButton::indicator { border-radius: 9px; }

/* ── Списки и деревья ─────────────────────────────────────────────── */
QTreeWidget, QListView, QListWidget {
  background: %(win)s; border: 0; padding: 5px;
  alternate-background-color: %(panel)s;
}
QTreeWidget::item, QListWidget::item { padding: 8px 10px; border-radius: 10px; }
QTreeWidget::item:hover, QListWidget::item:hover { background: %(hover)s; }
QTreeWidget::item:selected, QListWidget::item:selected, QListView::item:selected {
  background: %(sel)s; color: %(text)s;
}
QHeaderView::section { background: %(panel)s; border: 0; padding: 7px; color: %(dim)s; border-radius: 6px; }

/* ── Полосы прокрутки ─────────────────────────────────────────────── */
QScrollBar:vertical { background: transparent; width: 11px; margin: 3px; }
QScrollBar::handle:vertical { background: %(thumb)s; min-height: 36px; border-radius: 7px; }
QScrollBar::handle:vertical:hover { background: %(accent)s; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 3px; }
QScrollBar::handle:horizontal { background: %(thumb)s; min-width: 36px; border-radius: 7px; }
QScrollBar::handle:horizontal:hover { background: %(accent)s; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: %(panel)s; }

/* ── Слайдеры и прогресс ──────────────────────────────────────────── */
QSlider::groove:horizontal { height: 6px; background: %(track)s; border-radius: 3px; }
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 3px; }
QSlider::handle:horizontal {
  background: %(field)s; border: 2px solid %(accent)s;
  width: 14px; height: 14px; margin: -7px 0; border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: %(accent)s; }
QProgressBar {
  background: %(track)s; border: 0; border-radius: 10px; height: 10px;
  text-align: center; color: transparent;
}
QProgressBar::chunk { background: %(accent)s; border-radius: 10px; }
QSplitter::handle { background: %(divider)s; width: 1px; }
QSplitter::handle:hover { background: %(accent)s; }

/* ── Панель живой настройки рендера ───────────────────────────────── */
QWidget#TuneBar { background: %(panel)s; border-top: 1px solid %(divider)s; }
QWidget#TuneBar QLabel { color: %(dim)s; font-size: 10.5px; font-weight: 600; }
QWidget#TuneBar QComboBox, QWidget#TuneBar QSpinBox {
  padding: 6px 9px; font-size: 12px; border-radius: 9px;
}
QWidget#TuneBar QSlider { min-width: 76px; max-width: 102px; }
QWidget#TuneBar QPushButton { padding: 7px 14px; border-radius: 10px; }
QLabel#VSep { background: %(divider)s; max-width: 1px; min-width: 1px; margin: 2px 1px; }
QLabel#Chip {
  background: %(chip)s; color: %(dim)s; border-radius: 10px;
  padding: 3px 9px; font-size: 11px;
}
QLabel#EmptyState { background: transparent; color: %(dim)s; font-size: 14px; }

/* Продолжить чтение */
QFrame#ContinueBar {
  background: %(chip)s; border: 1px solid %(border)s; border-left: 3px solid %(accent)s;
  border-radius: 12px;
}
QLabel#ContinueLabel { color: %(text)s; font-size: 13px; font-weight: 600; }
QPushButton#ContinueBtn { background: %(accent)s; color: %(onaccent)s; border: 0; border-radius: 10px; font-weight: 600; }

QGroupBox {
  border: 1px solid %(border)s; border-radius: 12px;
  margin-top: 12px; padding: 12px 10px 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: %(dim)s; }
QDialogButtonBox { button-layout: 2; }
"""


def apply_theme(name, force=False):
    global _last
    app = QApplication.instance()
    if app is None:
        return
    name = norm_theme(name)
    if not force and _last == name:
        return
    _last = name
    th = THEMES[name]
    c = chrome(th)
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window, QColor(c["win"]))
    p.setColor(QPalette.WindowText, QColor(c["text"]))
    p.setColor(QPalette.Base, QColor(c["field"]))
    p.setColor(QPalette.AlternateBase, QColor(c["hover"]))
    p.setColor(QPalette.Text, QColor(c["text"]))
    p.setColor(QPalette.Button, QColor(c["hover"]))
    p.setColor(QPalette.ButtonText, QColor(c["text"]))
    p.setColor(QPalette.Highlight, QColor(c["accent"]))
    p.setColor(QPalette.HighlightedText, QColor(c["onaccent"]))
    p.setColor(QPalette.ToolTipBase, QColor(c["field"]))
    p.setColor(QPalette.ToolTipText, QColor(c["text"]))
    p.setColor(QPalette.PlaceholderText, QColor(c["dim"]))
    p.setColor(QPalette.Link, QColor(c["accent2"]))
    p.setColor(QPalette.LinkVisited, QColor(c["accent2"]))
    p.setColor(QPalette.Mid, QColor(c["border"]))
    p.setColor(QPalette.Dark, QColor(c["divider"]))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(c["dim"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["dim"]))
    app.setPalette(p)
    app.setStyleSheet(TPL % c)
