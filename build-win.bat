:: build_win.bat
pip install pyinstaller "PySide6>=6.6" charset-normalizer
pyinstaller main.py --name LightRead --noconsole --onedir ^
  --hidden-import PySide6.QtPdf --hidden-import PySide6.QtTextToSpeech ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtQuick3D --exclude-module PySide6.QtDesigner ^
  --exclude-module tkinter --exclude-module numpy
:: portable-режим: создайте файл portable.txt рядом с LightRead.exe