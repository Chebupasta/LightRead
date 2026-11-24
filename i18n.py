"""Перевод интерфейса RU/EN без изменения пользовательских данных."""
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QToolButton, QCheckBox,
                               QComboBox, QTabWidget, QMenu, QToolBar, QGroupBox, QLineEdit, QTabBar)
from PySide6.QtGui import QAction

from common import S

# каноническая строка интерфейса (RU) -> английский вариант
T = {
    "Главная": "Home", "Библиотека": "Library", "Книга": "Book", "Файл": "File",
    "книга": "book", "книги": "books", "книг": "books", "прочитано": "read",
    "в библиотеке · прогресс чтения": "in the library · reading progress",
    "Вид": "View", "Справка": "Help", "Открыть": "Open", "Открыть файл…": "Open file…",
    "Открыть файл": "Open file", "Поиск по библиотеке…": "Search the library…",
    "Новые": "Newest", "Настройки": "Settings", "Все вкладки": "All tabs",
    "★ Избранное": "★ Favorites", "Горячие клавиши": "Keyboard shortcuts",
    "О программе": "About", "Выход": "Quit", "Сетка / Список": "Grid / List",
    "Дерево": "Tree", "Дерево библиотеки": "Library tree", "Обложки": "Covers",
    "Сканировать": "Scan", "Папки": "Folders", "Выбрать папку библиотеки…": "Choose library folder…",
    "Добавить папку…": "Add folder…", "Догрузить обложки": "Fetch covers",
    "Все заметки…": "All notes…", "Все заметки": "All notes", "Свойства файла…": "File properties…",
    "Резервная копия…": "Backup…", "Восстановить из копии…": "Restore from backup…",
    "Искать по всем книгам…": "Search all books…", "Случайная книга": "Random book",
    "Обновить из репозитория…": "Update from repository…", "Поделиться": "Share",
    "Книгой (ссылка на файл)": "Book (file link)", "Страницей (ссылка с позицией)": "Page (position link)",
    "Снимком страницы": "Page screenshot", "Печать": "Print", "Всю книгу…": "Whole book…",
    "Текущую страницу/главу…": "Current page/chapter…", "Информация о книге": "Book information",
    "Таймер сна: 15 мин": "Sleep timer: 15 min", "Таймер сна: 30 мин": "Sleep timer: 30 min",
    "Таймер сна: 60 мин": "Sleep timer: 60 min", "Таймер сна: выкл": "Sleep timer: off",
    "Таймер чтения: старт/стоп": "Reading timer: start/stop",
    "Сохранить настройки для этой книги": "Save settings for this book",
    "Сбросить настройки книги": "Reset book settings", "Экспорт заметок…": "Export notes…",
    "Параметры": "Preferences", "Предыдущая глава": "Previous chapter",
    "Следующая глава": "Next chapter", "Содержание": "Contents", "Поиск": "Search",
    "Предыдущее совпадение": "Previous match", "Следующее совпадение": "Next match",
    "Закладка": "Bookmark", "Заметки": "Notes", "Озвучка": "Read aloud",
    "Автопрокрутка": "Autoscroll", "Авто": "Auto", "Тема": "Theme",
    "Полный экран": "Full screen", "Фокус-режим": "Focus mode", "Фокус": "Focus",
    "Сброс": "Reset", "Копировать": "Copy", "Выделить цветом": "Highlight color",
    "Выделить с заметкой…": "Highlight with note…", "Найти в словаре": "Look up",
    "Перевести в браузере": "Translate in browser", "Читать вслух отсюда": "Read aloud from here",
    "Заметка к странице…": "Note on page…", "Поиск в книге": "Find in book",
    "Выделить всё и скопировать": "Select all and copy", "Копировать страницу": "Copy page",
    "Продолжить чтение": "Continue reading", "Продолжить →": "Continue →",
    "Статистика": "Statistics", "Всего книг": "Total books", "Прочитано": "Finished",
    "Читаю сейчас": "Reading now", "Время чтения": "Reading time", "Страниц": "Pages",
    "Серия дней": "Day streak", "Закладки": "Bookmarks", "Заметки": "Notes",
    "Активность чтения · 90 дней": "Reading activity · 90 days",
    "Цитата дня · случайная из ваших заметок": "Quote of the day · from your notes",
    "Поделиться": "Share", "Открыть файл…": "Open file…",
    "Перейти в библиотеку": "Go to library", "Нет данных за период": "No data for this period",
    "Все книги": "All books", "Читаю": "Reading", "Прочитано": "Finished",
    "Планирую": "Planned", "Непрочитанные": "Unread", "Избранное": "Favorites",
    "Недавние": "Recent", "Презентации": "Presentations", "Метки": "Tags",
    "Коллекции": "Collections", "Умные коллекции": "Smart collections", "Авторы": "Authors",
    "Серии": "Series", "Форматы": "Formats", "Папки": "Folders",
    "Нет книг": "No books", "Добавить файл через «Файл → Открыть файл…»": "Add a file via File → Open file…",
    "или перетащите книгу прямо в окно": "or drag a book into the window",
    "Книг:": "Books:", "Светлая": "Light", "Тёмная": "Dark",
    "Чтение": "Reading", "PDF и сканы": "PDF & scans", "Управление": "Controls",
    "Сервисы": "Services", "Библиотека": "Library",
    "Шрифт": "Font", "Кегль, pt": "Size, pt", "Полужирный": "Bold",
    "Межстрочный, %": "Line spacing, %", "Абзацный отступ": "Indent",
    "Отступ между абзацами": "Paragraph spacing", "Выключка": "Alignment",
    "Поля": "Margins", "Колонок": "Columns", "Режим": "Mode",
    "Яркость": "Brightness", "Мягкие переносы (текстовые книги)": "Soft hyphens (text books)",
    "Office: точный вид через PDF (1:1)": "Office: exact PDF rendering (1:1)",
    "Хранить кэш PDF, дней": "Keep PDF cache, days", "Лимит кэша PDF, МБ": "PDF cache limit, MB",
    "Подгонка": "Fit", "Масштаб": "Zoom", "Зазор": "Gap", "Резкость": "Sharpness",
    "Скан": "Scan", "Обрезать поля": "Crop margins", "Ночь": "Night",
    "Инверсия в ночи": "Invert at night", "По ширине": "Fit width",
    "По странице": "Fit page", "Своя": "Custom", "Обычная": "Normal",
    "Высокая": "High", "Максимум": "Maximum", "Страницы": "Pages", "Свиток": "Scroll",
    "Название": "Title", "Автор": "Author", "Серия": "Series", "Номер": "No.",
    "Язык": "Language", "Жанры": "Genres", "Голос TTS": "TTS voice",
    "Скорость": "Rate", "Тон": "Pitch", "Громкость": "Volume",
    "Автоперелистывание при озвучке": "Auto page turn while speaking",
    "Папки словарей StarDict": "StarDict folders", "WebDAV URL": "WebDAV URL",
    "WebDAV пользователь": "WebDAV user", "WebDAV пароль": "WebDAV password",
    "Синхронизировать при закрытии": "Sync on close", "URL релизов (GitHub API)": "Release URL (GitHub API)",
    "Проверять обновления при запуске": "Check updates on startup",
    "Показывать сетевые функции": "Show network features",
    "URL git-репозитория для автообновления": "Git repository URL for auto-update",
    "Обновляться из репозитория при запуске": "Update from repository on startup",
    "Папки сканирования": "Scan folders", "Сканировать при запуске": "Scan on startup",
    "Запоминать настройки для каждой книги": "Remember settings per book",
    "Тема чтения": "Reading theme", "Акцентный цвет": "Accent color",
    "Тап-зоны": "Tap zones", "Колесо листает страницы": "Wheel turns pages",
    "Горизонтальный свайп листает страницы": "Horizontal swipe turns pages",
    "Скорость автопрокрутки": "Autoscroll speed", "Панель настройки при открытии": "Tuning panel on open",
    "Цель чтения не задана — F7 → Сервисы": "No reading goal — F7 → Services",
    "Язык интерфейса": "Interface language", "Русский": "Russian", "English": "English",
    "Здесь появятся недавно открытые книги": "Recently opened books will appear here",
    "Подготовка точного вида (PDF)…": "Preparing exact view (PDF)…", "Отмена": "Cancel",
    "Ошибка открытия": "Open error", "Нет файла": "File unavailable",
    "Обновления": "Updates", "Доступна версия": "Version available",
    "Удалить": "Delete", "Удалить заметку": "Delete note",
    "Удалить выбранную заметку?": "Delete the selected note?",
    "Введите текст заметки": "Enter note text", "Заметка сохранена": "Note saved",
    "Цитата скопирована": "Quote copied", "Ссылка скопирована": "Link copied",
    "Ссылка на страницу скопирована": "Page link copied",
    "Снимок страницы скопирован": "Page screenshot copied",
    "Таймер чтения запущен": "Reading timer started", "Таймер чтения остановлен": "Reading timer stopped",
    "Перерыв — отдохните": "Break — take a rest", "Пора читать": "Time to read",
    "Отправлено на печать": "Sent to printer", "Приложение обновлено": "Application updated",
    "Обновлений нет": "No updates", "Перезапустить приложение?": "Restart the application?",
}


def ui_text(text):
    return text if S.get("language", "ru") == "ru" else T.get(text, text)


def _translate(obj, getter, setter, prop="_lr_text"):
    original = obj.property(prop)
    if original is None:
        original = getter()
        obj.setProperty(prop, original)
    if not isinstance(original, str):
        return
    setter(original if S.get("language", "ru") == "ru" else T.get(original, original))


def apply_language(root):
    """Применить выбранный язык ко всем найденным строкам интерфейса."""
    if root is None:
        return
    widgets = [root] + list(root.findChildren(QWidget))
    for w in widgets:
        if isinstance(w, QLabel) or isinstance(w, (QPushButton, QToolButton, QCheckBox, QGroupBox)):
            _translate(w, w.text, w.setText)
        if isinstance(w, QLineEdit):
            _translate(w, w.placeholderText, w.setPlaceholderText, "_lr_placeholder")
        _translate(w, w.windowTitle, w.setWindowTitle, "_lr_title")
        _translate(w, w.toolTip, w.setToolTip, "_lr_tip")
        if isinstance(w, QComboBox) and not w.isEditable():
            original = w.property("_lr_items")
            if original is None:
                original = [w.itemText(i) for i in range(w.count())]
                w.setProperty("_lr_items", original)
            for i, text in enumerate(original):
                w.setItemText(i, text if S.get("language", "ru") == "ru" else T.get(text, text))
        tab_bar = w.tabBar() if isinstance(w, QTabWidget) else (w if isinstance(w, QTabBar) else None)
        if tab_bar is not None:
            original = tab_bar.property("_lr_tabs")
            if original is None:
                original = [tab_bar.tabText(i) for i in range(tab_bar.count())]
                tab_bar.setProperty("_lr_tabs", original)
            for i, text in enumerate(original):
                tab_bar.setTabText(i, text if S.get("language", "ru") == "ru" else T.get(text, text))
    for action in root.findChildren(QAction):
        _translate(action, action.text, action.setText)
        _translate(action, action.toolTip, action.setToolTip, "_lr_tip")
    for menu in root.findChildren(QMenu):
        _translate(menu, menu.title, menu.setTitle, "_lr_title")
