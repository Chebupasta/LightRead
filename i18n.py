"""Перевод интерфейса RU/EN без изменения пользовательских данных."""
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QToolButton, QCheckBox,
                               QComboBox, QTabWidget, QMenu, QToolBar, QGroupBox, QLineEdit, QTabBar)
from PySide6.QtGui import QAction
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QMenuBar

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
    # --- настройки и диалоги ---
    "Настройки приложения": "Application settings", "Свойства файла": "File properties",
    "Формат": "Format", "Путь": "Path", "Папка": "Folder", "Имя файла": "File name",
    "Размер в библиотеке": "Size in library", "Добавлен в библиотеку": "Added to library",
    "Статус": "Status", "Прогресс": "Progress", "Общие": "General", "Метаданные": "Metadata",
    "Открыть папку": "Open folder", "Копировать путь": "Copy path", "Закрыть": "Close",
    "О книге": "About book", "Сведения о книге": "Book details", "Аннотация": "Annotation",
    "Аннотация:": "Annotation:", "Новая метка…": "New tag…",
    "Загрузить свою обложку…": "Upload custom cover…", "Сохранить": "Save",
    "Метка": "Tag", "Название метки:": "Tag name:", "Обложка книги": "Book cover",
    "Изображения (*.png *.jpg *.jpeg *.webp)": "Images (*.png *.jpg *.jpeg *.webp)",
    "Статистика чтения": "Reading statistics", "Нажми на день, чтобы увидеть детали": "Click a day for details",
    "OPDS-каталоги": "OPDS catalogs", "Каталоги OPDS": "OPDS catalogs",
    "Добавить каталог…": "Add catalog…", "Выбери каталог": "Choose a catalog",
    "Скачать в библиотеку": "Download to library", "Название каталога:": "Catalog name:",
    "URL фида (Atom):": "Feed URL (Atom):",
    "Поиск по заметкам, цитатам и книгам…": "Search notes, quotes and books…",
    "Главный экран": "Home screen", "Ваши книги и прогресс чтения": "Your books and reading progress",
    "Уведомление": "Notification", "Умная коллекция": "Smart collection",
    "Правило умной коллекции": "Smart collection rule", "Любой": "Any", "Любая": "Any",
    "Только избранное": "Favorites only", " дней": " days", "Команды": "Commands",
    "Палитра команд": "Command palette", "Книга или команда…": "Book or command…",
    "База данных была повреждена и пересоздана": "Database was corrupted and recreated",
    "Поиск по библиотеке": "Library search", "Навигация по библиотеке": "Library navigation",
    "Книги библиотеки": "Library books", "Вкладки книг": "Book tabs",
    "Новая коллекция…": "New collection…", "Новая умная коллекция…": "New smart collection…",
    "Коллекция": "Collection", "Название коллекции": "Collection name",
    "Папка с книгами (сканировать со вложенными)": "Books folder (scan subfolders)",
    "Добавить папку с книгами": "Add books folder", "Открыть книги": "Open books",
    "Глобальный поиск по книгам": "Global book search", "Фраза во всех книгах…": "Phrase in all books…",
    "Поисковая фраза": "Search phrase", "Результаты поиска": "Search results",
    "Введите минимум 2 символа": "Enter at least 2 characters", "Поиск по всем книгам": "Search all books",
    "Закрыть вкладку": "Close tab", "В коллекцию": "Add to collection", "Новая…": "New…",
    "Сбросить прогресс": "Reset progress", "Убрать из библиотеки": "Remove from library",
    "Удалить файлы…": "Delete files…", "Доступна версия: ": "Version available: ",
    "Резервная копия": "Backup", "Готово": "Done", "Копия сохранена.": "Backup saved.",
    "Восстановить": "Restore", "Восстановлено. Перезапустите LightRead.": "Restored. Restart LightRead.",
    "ЧИТАЮ": "READING", "ПРОЧИТАНО": "FINISHED", "ПЛАН": "PLANNED",
    "Зазор колонок": "Column gap", "Масштаб, %": "Zoom, %", "Обрезать поля скана": "Crop scan margins",
    "Инверсия в тёмной теме": "Invert in dark theme", "Зазор между страницами": "Page gap",
    "Тень страницы": "Page shadow", "Резкость рендера": "Render sharpness",
    "Менять тему по времени суток": "Auto theme by time of day", "Светлая с часа": "Light from hour",
    "Тёмная с часа": "Dark from hour", "Таймер чтения, мин": "Reading timer, min",
    "Перерыв, мин": "Break, min", "Панель библиотеки при чтении": "Library toolbar while reading",
    "Файл на диске": "File on disk", "Недоступен": "Unavailable", "Размер на диске": "Size on disk",
    "Создан": "Created", "Изменён": "Modified", "Последний доступ": "Last accessed",
    "Заголовок": "Title", "Номер в серии": "Series number", "Не удалось прочитать": "Failed to read",
    "<b>Формат:</b> ": "<b>Format:</b> ", "<br><b>Прогресс:</b> ": "<br><b>Progress:</b> ",
    "%<br><b>Чтение:</b> ": "%<br><b>Reading:</b> ", "<br><b>Путь:</b> ": "<br><b>Path:</b> ",
    "Статус:": "Status:", "Коллекции:": "Collections:", "Метки:": "Tags:",
    "<h3>Статистика чтения</h3>": "<h3>Reading statistics</h3>", "Период:": "Period:",
    "7 дней": "7 days", "30 дней": "30 days", "90 дней": "90 days",
    "Цель, мин/день:": "Goal, min/day:", "Каталоги:": "Catalogs:",
    "У книги нет ссылки на скачивание": "Book has no download link", "Без названия": "Untitled",
    "Не начата": "Not started", " — библиотека": " — library", "Недавно читал": "Recently read",
    "Размер": "Size", "OPDS-каталоги…": "OPDS catalogs…",
    "Синхронизация: отправить": "Sync: upload", "Синхронизация: получить": "Sync: download",
    "Проверить обновления…": "Check for updates…", "Все книги (": "All books (",
    "Презентации (": "Presentations (", "Изменить правило…": "Edit rule…",
    "Удалить правило": "Delete rule", "Удалить коллекцию": "Delete collection",
    "Удалить метку": "Delete tag", "Книг: ": "Books: ", "Добро пожаловать": "Welcome",
    "Библиотека пуста. Выбрать папку с книгами?": "Library is empty. Choose a books folder?",
    "Папка библиотеки: ": "Library folder: ",
    "Эта папка уже есть в библиотеке": "This folder is already in the library",
    "Сканирование завершено: +": "Scan complete: +", "Обложки: ": "Covers: ",
    "Книги (": "Books (", ");;Все файлы (*)": ");;All files (*)",
    "Ищу по всем книгам…": "Searching all books…", "⌂ Главная": "⌂ Home",
    "Читать": "Read", "Информация…": "Info…", "В избранное": "Add to favorites",
    "Обновить обложку": "Refresh cover", "Показать в папке": "Show in folder",
    "Удалить файл с диска?": "Delete file from disk?", "Обновление": "Update",
    "Укажи WebDAV URL в настройках": "Set WebDAV URL in settings",
    "Синхронизация: данные получены": "Sync: data received",
    "Не указан URL репозитория": "Repository URL not specified",
    "Папка приложения не является git-репозиторием": "App folder is not a git repository",
    "Есть локальные изменения — обновление пропущено": "Local changes present — update skipped",
    "Не удалось получить обновления из репозитория": "Could not fetch updates from repository",
    "Автор не указан": "Unknown author", "Открыт для записи": "Open for writing",
    "Идентификатор": "Identifier", "Путь скопирован": "Path copied",
    "Всего времени: <b>": "Total time: <b>", "</b> · Страниц: <b>": "</b> · Pages: <b>",
    "</b> · Серия дней: <b>": "</b> · Day streak: <b>", "(без названия)": "(untitled)",
    "Скачано: ": "Downloaded: ", "Цель на сегодня: ": "Today's goal: ",
    ". Копия: ": ". Copy: ", "Файл недоступен: ": "File unavailable: ",
    "Озвучка: вкл/выкл": "Read aloud: on/off", "Следующая страница": "Next page",
    "Удалить ": "Delete ", " файлов с диска?": " files from disk?",
    "Укажи URL релизов в настройках": "Set release URL in settings",
    "Не удалось проверить: ": "Check failed: ", "Синхронизация: данные отправлены": "Sync: data sent",
    "Не удалось обновить: ": "Update failed: ", "да": "yes", "нет": "no",
    "Самый продуктивный день: <b>": "Most productive day: <b>", "цель выполнена": "goal reached",
    " · есть следующая страница": " · next page available", "Ошибка каталога: ": "Catalog error: ",
    "Ошибка скачивания: ": "Download error: ",
    "</b><br>Читалка на Qt6.<br>Данные: ": "</b><br>Reader on Qt6.<br>Data: ",
    "Обложки готовы": "Covers ready", "Не удалось открыть": "Could not open",
    " · гл. ": " · ch. ", "Найдено: ": "Found: ", "Доступна версия ": "Version available ",
    "Ошибка синхронизации: ": "Sync error: ", "до цели ": "to goal ",
    "Скан: ": "Scan: ", "Выбрано книг: ": "Books selected: ",
    # --- окно чтения ---
    "Ссылка на книгу скопирована": "Book link copied", "Снимок страницы в буфере": "Page screenshot in clipboard",
    "Настройка": "Settings", "Навигация": "Navigation", "Оглавление книги": "Book contents",
    "Заметки книги": "Book notes", "Редактор заметки": "Note editor", "Текст заметки…": "Note text…",
    "Новая": "New", "Текст в книге…": "Text in book…", "Поиск по книге": "Find in book",
    "0 совп.": "0 matches", "Слово…": "Word…", "Словарь": "Dictionary",
    "Озвучка не активна": "Read aloud is not active", "Настройка рендера": "Render settings",
    "Переименовать…": "Rename…", "Удалить закладку": "Delete bookmark", "Название:": "Name:",
    "Изменить заметку…": "Edit note…", "Экспорт всех…": "Export all…",
    "Введите заметку и нажми «Сохранить»": "Enter a note and press Save",
    "Экспорт заметок": "Export notes",
    "Markdown (*.md);;Текст (*.txt);;HTML (*.html);;JSON (*.json)": "Markdown (*.md);;Text (*.txt);;HTML (*.html);;JSON (*.json)",
    "Закладка добавлена": "Bookmark added", "Поиск…": "Search…",
    "Совпадений нет: у скана может отсутствовать текстовый слой": "No matches: the scan may have no text layer",
    "Движок TTS недоступен.": "TTS engine unavailable.",
    "Настройки сохранены для этой книги": "Settings saved for this book",
    "Кегль": "Size", "Интерлиньяж": "Line spacing", "Отступ": "Indent", "Колонки": "Columns",
    "◀ совп": "◀ match", "совп ▶": "match ▶", "Сейчас читает:": "Now reading:", "Далее:": "Next:",
    "стр.": "p.", "гл.": "ch.", "Экспорт": "Export", "Заметок пока нет.": "No notes yet.",
    "чтение": "reading", "перерыв": "break", "Стр. ": "P. ", "Заметка": "Note",
    "Комментарий:": "Comment:", " совп.": " matches",
    "Словари не найдены или слово отсутствует.<br><a href='https://ru.wiktionary.org/wiki/": "No dictionaries found or word missing.<br><a href='https://ru.wiktionary.org/wiki/",
    "'>Викисловарь</a> · <a href='https://translate.google.com/?text=": "'>Wiktionary</a> · <a href='https://translate.google.com/?text=",
    "'>Перевод</a><br><br><i>Папка со словарями StarDict: F7 → Сервисы.</i>": "'>Translate</a><br><br><i>StarDict folder: F7 → Services.</i>",
    "Настройки: ": "Settings: ", ", гл. ": ", ch. ", "  гл.": "  ch.", "стр. ": "p. ",
    "гл. ": "ch. ", "Оглавление: ": "Contents: ", "Таймер сна: ": "Sleep timer: ",
    " мин": " min", "Кегль: ": "Size: ", "Тема: ": "Theme: ", "Сохранено: ": "Saved: ",
    "</h3><p>Автор: ": "</h3><p>Author: ", "<br>Серия: ": "<br>Series: ",
    "<br>Формат: ": "<br>Format: ", "<br>Прогресс: ": "<br>Progress: ",
    "%<br>Время чтения: ": "%<br>Reading time: ", "<br>Файл: ": "<br>File: ",
    "Автор: ": "Author: ", "Серия: ": "Series: ", "Формат: ": "Format: ",
    "Прогресс: ": "Progress: ", "Время чтения: ": "Reading time: ", "Файл: ": "File: ",
    "· гл.": "· ch.", "  гл.": "  ch.", "Часть ": "Part ",
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
    # сам перевод не должен вызывать логику виджета (например, запись настройки)
    blocked = obj.signalsBlocked()
    obj.blockSignals(True)
    try:
        setter(original if S.get("language", "ru") == "ru" else T.get(original, original))
    finally:
        obj.blockSignals(blocked)


class _DialogLanguageFilter(QObject):
    """Переводит диалоги и меню, открываемые уже после запуска приложения."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Show and isinstance(obj, (QDialog, QMenu)):
            if not obj.property("_lr_dialog_done"):
                obj.setProperty("_lr_dialog_done", True)
                apply_language(obj)
        return False


_lang_filter = None


def _ensure_filter():
    global _lang_filter
    app = QApplication.instance()
    if app is not None and _lang_filter is None:
        _lang_filter = _DialogLanguageFilter(app)
        app.installEventFilter(_lang_filter)


def apply_language(root):
    """Применить выбранный язык ко всем найденным строкам интерфейса."""
    if root is None:
        return
    _ensure_filter()
    widgets = [root] + list(root.findChildren(QWidget))
    ru = S.get("language", "ru") == "ru"
    for w in widgets:
        if isinstance(w, QLabel) or isinstance(w, (QPushButton, QToolButton, QCheckBox, QGroupBox)):
            _translate(w, w.text, w.setText)
        if isinstance(w, QLineEdit):
            _translate(w, w.placeholderText, w.setPlaceholderText, "_lr_placeholder")
        _translate(w, w.windowTitle, w.setWindowTitle, "_lr_window_title")
        _translate(w, w.toolTip, w.setToolTip, "_lr_tip")
        if isinstance(w, QComboBox) and not w.isEditable():
            original = w.property("_lr_items")
            if original is None:
                original = [w.itemText(i) for i in range(w.count())]
                w.setProperty("_lr_items", original)
            blocked = w.signalsBlocked(); w.blockSignals(True)
            try:
                for i, text in enumerate(original):
                    w.setItemText(i, text if ru else T.get(text, text))
            finally:
                w.blockSignals(blocked)
        if isinstance(w, QTabWidget):
            original = w.property("_lr_tabs")
            if original is None or len(original) != w.count():
                original = list(original or [])
                original = [original[i] if i < len(original) else w.tabText(i)
                            for i in range(w.count())]
                w.setProperty("_lr_tabs", original)
            blocked = w.signalsBlocked(); w.blockSignals(True)
            try:
                for i in range(w.count()):
                    tab_widget = w.widget(i)
                    canonical = tab_widget.property("_lr_tab_title") if tab_widget is not None else None
                    text = canonical if canonical is not None else original[i]
                    w.setTabText(i, text if ru else T.get(text, text))
            finally:
                w.blockSignals(blocked)
        elif isinstance(w, QTabBar):
            original = w.property("_lr_tabs")
            if original is None or len(original) != w.count():
                original = list(original or [])
                original = [original[i] if i < len(original) else w.tabText(i)
                            for i in range(w.count())]
                w.setProperty("_lr_tabs", original)
            blocked = w.signalsBlocked(); w.blockSignals(True)
            try:
                for i, text in enumerate(original):
                    w.setTabText(i, text if ru else T.get(text, text))
            finally:
                w.blockSignals(blocked)
    # у QMenu текст пункта в менюбаре привязан к заголовку меню — переводим его явно
    bars = root.findChildren(QMenuBar)
    if isinstance(root, QMenuBar):
        bars = [root] + bars
    elif hasattr(root, "menuBar"):
        try:
            bar = root.menuBar()
        except Exception:
            bar = None
        if bar is not None:
            bars = [bar] + bars
    for bar in bars:
        for action in bar.actions():
            menu = action.menu()
            if menu is not None:
                _translate(menu, menu.title, menu.setTitle, "_lr_menu_title")
    for action in root.findChildren(QAction):
        _translate(action, action.text, action.setText)
        _translate(action, action.toolTip, action.setToolTip, "_lr_tip")
    for menu in root.findChildren(QMenu):
        _translate(menu, menu.title, menu.setTitle, "_lr_menu_title")
