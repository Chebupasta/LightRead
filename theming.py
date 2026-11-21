"""Применение токенов: обвязка приложения следует за темой чтения.

Источник правды — common.py (primitive → semantic → chrome). Здесь только
раскладка QSS и QPalette поверх готового словаря токенов.
"""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from common import THEMES, chrome, norm_theme

_last = None


TPL = """
* { outline: 0; }

QWidget {
  background: %(bg.canvas)s; color: %(text.primary)s;
  font-family: "Inter", "Segoe UI", "Noto Sans", "Helvetica Neue", sans-serif;
  font-size: %(font.lg)s; font-weight: %(font.weight.regular)s;
}
QMainWindow, QDialog { background: %(bg.canvas)s; }
QFrame { border-radius: %(radius.sm)s; }
QToolTip {
  background: %(bg.panel)s; color: %(text.primary)s;
  border: 1px solid %(border.strong)s; border-radius: %(radius.sm)s;
  padding: 6px 9px;
}

/* ── Меню ─────────────────────────────────────────────────────────── */
QMenuBar {
  background: %(bg.canvas)s; padding: 2px %(space.sm)s;
  border-bottom: 1px solid %(border.subtle)s;
}
QMenuBar::item {
  padding: 5px 10px; border-radius: %(radius.sm)s;
  background: transparent; color: %(text.secondary)s;
}
QMenuBar::item:selected { background: %(bg.hover)s; color: %(text.primary)s; }
QMenu {
  background: %(bg.panel)s; border: 1px solid %(border.subtle)s;
  border-radius: %(radius.md)s; padding: 4px;
}
QMenu::item {
  padding: 6px 22px 6px 10px; border-radius: %(radius.sm)s; color: %(text.primary)s;
}
QMenu::item:selected { background: %(bg.hover)s; color: %(text.primary)s; }
QMenu::separator { height: 1px; background: %(border.subtle)s; margin: 4px 6px; }

/* ── Панели инструментов ──────────────────────────────────────────── */
QToolBar {
  background: %(bg.canvas)s; border: 0; border-bottom: 1px solid %(border.subtle)s;
  padding: 4px %(space.md)s; spacing: 2px;
}
QToolButton {
  background: transparent; color: %(text.secondary)s; padding: 5px 9px;
  border-radius: %(radius.sm)s; border: 1px solid transparent; font-size: %(font.md)s;
}
QToolButton:hover { background: %(bg.hover)s; color: %(text.primary)s; }
QToolButton:pressed { background: %(bg.selected)s; }
QToolButton:checked {
  background: %(accent.subtle)s; color: %(accent.hover)s; border-color: transparent;
}
QToolBar::separator { width: 1px; background: %(border.subtle)s; margin: 4px 6px; }

/* ── Статус-бар ───────────────────────────────────────────────────── */
QStatusBar {
  background: %(bg.canvas)s; border-top: 1px solid %(border.subtle)s;
  color: %(text.tertiary)s;
}
QStatusBar QLabel {
  color: %(text.secondary)s; padding: 0 %(space.sm)s;
  font-size: %(font.sm)s; border-radius: %(radius.sm)s;
}
QStatusBar::item { border: 0; }
QStatusBar QSpinBox { padding: 2px 4px; font-size: %(font.sm)s; border-radius: %(radius.sm)s; }
QStatusBar QSlider { max-height: 14px; border-radius: %(radius.sm)s; }

/* ── Док-панель и вкладки ─────────────────────────────────────────── */
QDockWidget { color: %(text.secondary)s; border-radius: %(radius.md)s; }
QDockWidget::title {
  background: %(bg.canvas)s; padding: 6px 10px;
  border-bottom: 1px solid %(border.subtle)s;
  border-radius: %(radius.sm)s %(radius.sm)s 0 0;
  font-size: %(font.sm)s;
}
QTabWidget::pane { border: 0; background: %(bg.canvas)s; top: -1px; border-radius: %(radius.sm)s; }
QTabBar::tab {
  background: transparent; color: %(text.tertiary)s; padding: 6px 12px;
  border-bottom: 2px solid transparent; margin: 0 2px;
  border-radius: %(radius.sm)s %(radius.sm)s 0 0;
}
QTabBar::tab:selected {
  color: %(text.primary)s; border-bottom: 2px solid %(accent.default)s; background: transparent;
}
QTabBar::tab:hover:!selected { color: %(text.primary)s; background: %(bg.hover)s; }

/* ── Поля ввода ───────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextBrowser, QFontComboBox {
  background: %(bg.field)s; border: 1px solid %(border.subtle)s;
  border-radius: %(radius.sm)s; padding: 5px 8px; color: %(text.primary)s;
  selection-background-color: %(accent.subtle)s; selection-color: %(text.primary)s;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QTextBrowser:focus { border-color: %(border.focus)s; }
QComboBox::drop-down { border: 0; width: 16px; }
QComboBox QAbstractItemView {
  background: %(bg.panel)s; border: 1px solid %(border.subtle)s;
  border-radius: %(radius.sm)s; padding: 4px;
  selection-background-color: %(bg.hover)s; selection-color: %(text.primary)s;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
  width: 14px; background: transparent; border: 0; border-radius: %(radius.xs)s;
}

/* ── Кнопки и переключатели ───────────────────────────────────────── */
QPushButton {
  background: %(bg.field)s; border: 1px solid %(border.subtle)s;
  border-radius: %(radius.sm)s; padding: 6px 12px; color: %(text.primary)s;
}
QPushButton:hover { background: %(bg.hover)s; border-color: %(border.strong)s; }
QPushButton:pressed { background: %(bg.selected)s; }
QPushButton:default {
  background: %(accent.default)s; color: %(text.on_accent)s; border-color: %(accent.default)s;
  font-weight: %(font.weight.medium)s;
}
QPushButton:flat { border: 0; background: transparent; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator {
  width: 14px; height: 14px; border-radius: %(radius.xs)s;
  border: 1px solid %(border.strong)s; background: %(bg.field)s;
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: %(accent.default)s; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
  background: %(accent.default)s; border-color: %(accent.default)s;
}
QRadioButton::indicator { border-radius: 7px; }

/* ── Списки и деревья ─────────────────────────────────────────────── */
QTreeWidget, QListView, QListWidget {
  background: %(bg.canvas)s; border: 0; padding: 4px;
  alternate-background-color: %(bg.panel)s;
}
QTreeWidget::item, QListWidget::item { padding: 5px 8px; border-radius: %(radius.sm)s; }
QTreeWidget::item:hover, QListWidget::item:hover { background: %(bg.hover)s; }
QTreeWidget::item:selected, QListWidget::item:selected, QListView::item:selected {
  background: %(bg.selected)s; color: %(text.primary)s;
}
QHeaderView::section {
  background: %(bg.canvas)s; border: 0; padding: 5px;
  color: %(text.tertiary)s; border-radius: %(radius.xs)s;
}

/* ── Полосы прокрутки ─────────────────────────────────────────────── */
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical {
  background: %(border.strong)s; min-height: 24px; border-radius: %(radius.xs)s;
}
QScrollBar::handle:vertical:hover { background: %(text.tertiary)s; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal {
  background: %(border.strong)s; min-width: 24px; border-radius: %(radius.xs)s;
}
QScrollBar::handle:horizontal:hover { background: %(text.tertiary)s; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: %(bg.canvas)s; }

/* ── Слайдеры и прогресс ──────────────────────────────────────────── */
QSlider::groove:horizontal { height: 3px; background: %(bg.subtle)s; border-radius: %(radius.xs)s; }
QSlider::sub-page:horizontal { background: %(accent.default)s; border-radius: %(radius.xs)s; }
QSlider::handle:horizontal {
  background: %(bg.field)s; border: 1px solid %(accent.default)s;
  width: 12px; height: 12px; margin: -5px 0; border-radius: %(radius.sm)s;
}
QSlider::handle:horizontal:hover { background: %(accent.default)s; }
QProgressBar {
  background: %(bg.subtle)s; border: 0; border-radius: %(radius.xs)s; height: 3px;
  text-align: center; color: transparent;
}
QProgressBar::chunk { background: %(accent.default)s; border-radius: %(radius.xs)s; }
QSplitter::handle { background: %(border.subtle)s; width: 1px; }
QSplitter::handle:hover { background: %(accent.default)s; }

/* ── Панель живой настройки рендера ───────────────────────────────── */
QWidget#TuneBar { background: %(bg.panel)s; border-top: 1px solid %(border.subtle)s; }
QWidget#TuneBar QLabel { color: %(text.tertiary)s; font-size: %(font.sm)s; }
QWidget#TuneBar QComboBox, QWidget#TuneBar QSpinBox {
  padding: 4px 7px; font-size: %(font.md)s; border-radius: %(radius.sm)s;
}
QWidget#TuneBar QSlider { min-width: 64px; max-width: 92px; }
QWidget#TuneBar QPushButton { padding: 5px 10px; border-radius: %(radius.sm)s; }
QLabel#VSep { background: %(border.subtle)s; max-width: 1px; min-width: 1px; margin: 2px 1px; }
QLabel#Chip {
  background: %(bg.subtle)s; color: %(text.secondary)s;
  border-radius: %(radius.sm)s; padding: 2px 7px; font-size: %(font.sm)s;
}
QLabel#EmptyState { background: transparent; color: %(text.tertiary)s; font-size: %(font.xl)s; }

QFrame#Toast {
  background: %(bg.panel)s; border: 1px solid %(border.strong)s;
  border-radius: %(radius.sm)s;
}
QFrame#Toast QLabel { color: %(text.primary)s; font-size: %(font.md)s; }

/* Продолжить чтение */
QFrame#ContinueBar {
  background: %(bg.panel)s; border: 1px solid %(border.subtle)s;
  border-left: 2px solid %(accent.default)s; border-radius: %(radius.sm)s;
}
QLabel#ContinueLabel { color: %(text.primary)s; font-size: %(font.lg)s; }
QPushButton#ContinueBtn {
  background: %(accent.default)s; color: %(text.on_accent)s;
  border: 0; border-radius: %(radius.sm)s;
}

QGroupBox {
  border: 1px solid %(border.subtle)s; border-radius: %(radius.md)s;
  margin-top: 10px; padding: 10px 8px 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: %(text.tertiary)s; }
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
    c = chrome(THEMES[name])
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window, QColor(c["bg.canvas"]))
    p.setColor(QPalette.WindowText, QColor(c["text.primary"]))
    p.setColor(QPalette.Base, QColor(c["bg.field"]))
    p.setColor(QPalette.AlternateBase, QColor(c["bg.subtle"]))
    p.setColor(QPalette.Text, QColor(c["text.primary"]))
    p.setColor(QPalette.Button, QColor(c["bg.field"]))
    p.setColor(QPalette.ButtonText, QColor(c["text.primary"]))
    p.setColor(QPalette.Highlight, QColor(c["bg.selected"]))
    p.setColor(QPalette.HighlightedText, QColor(c["text.primary"]))
    p.setColor(QPalette.ToolTipBase, QColor(c["bg.panel"]))
    p.setColor(QPalette.ToolTipText, QColor(c["text.primary"]))
    p.setColor(QPalette.PlaceholderText, QColor(c["text.tertiary"]))
    p.setColor(QPalette.Link, QColor(c["accent.default"]))
    p.setColor(QPalette.LinkVisited, QColor(c["accent.hover"]))
    p.setColor(QPalette.Mid, QColor(c["border.subtle"]))
    p.setColor(QPalette.Dark, QColor(c["border.strong"]))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(c["text.tertiary"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["text.tertiary"]))
    app.setPalette(p)
    app.setStyleSheet(TPL % c)
