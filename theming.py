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
    """Параметры оформления «обвязки» приложения под текущую тему чтения."""
    if th["dark"]:
        return dict(
            win="#0f1216", panel="#161a20", field="#1d222a", border="#2c333d",
            text="#e9e7e2", dim="#939bab", hover="#222933", sel="#2b3644",
            accent=ACCENT, onaccent="#1b130e", accent2="#7aa7f7",
            track="#0a0d11", thumb="#37404d", divider="#252b34",
            chip="#202630", shadow="#46000000", page=th["desk"],
        )
    return dict(
        win="#f4f1eb", panel="#ebe6dc", field="#fffdf9", border="#dcd5c8",
        text="#2b2823", dim="#7d776c", hover="#e4ded2", sel="#dcd2c1",
        accent="#b8622f", onaccent="#fffaf5", accent2="#2f6f9e",
        track="#e7e1d6", thumb="#c7bdad", divider="#e1dace",
        chip="#ece5d8", shadow="#1c362a18", page=th["desk"],
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
QMenuBar { background: %(panel)s; padding: 3px 8px; border-bottom: 1px solid %(divider)s; }
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
QStatusBar QLabel { color: %(dim)s; padding: 0 8px; font-size: 12px; }
QStatusBar::item { border: 0; }
QStatusBar QSpinBox { padding: 3px 5px; font-size: 11px; }
QStatusBar QSlider { max-height: 18px; }

/* ── Док-панель и вкладки ─────────────────────────────────────────── */
QDockWidget { color: %(dim)s; }
QDockWidget::title {
  background: %(panel)s; padding: 9px 12px;
  border-bottom: 1px solid %(divider)s; font-size: 11px; font-weight: 600;
}
QTabWidget::pane { border: 0; background: %(win)s; top: -1px; }
QTabBar::tab {
  background: transparent; color: %(dim)s; padding: 9px 14px;
  border-bottom: 2px solid transparent; margin: 0 2px;
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
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox QAbstractItemView {
  background: %(field)s; border: 1px solid %(border)s; border-radius: 10px;
  padding: 5px; selection-background-color: %(accent)s; selection-color: %(onaccent)s;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
  width: 16px; background: transparent; border: 0;
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
QHeaderView::section { background: %(panel)s; border: 0; padding: 7px; color: %(dim)s; }

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
  border-radius: 0;
}
QLabel#ContinueLabel { color: %(text)s; font-size: 13px; font-weight: 600; }
QPushButton#ContinueBtn { background: %(accent)s; color: %(onaccent)s; border: 0; font-weight: 600; }

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
