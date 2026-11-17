#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --upgrade pyinstaller "PySide6>=6.6" charset-normalizer
pyinstaller main.py --name lightread --onedir \
  --hidden-import PySide6.QtPdf --hidden-import PySide6.QtTextToSpeech \
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets

# установка ярлыка (имя и расширение строго .desktop)
install -Dm644 settings.ini "$HOME/.local/share/applications/lightread.desktop"
if [ -f lightread.png ]; then
  install -Dm644 lightread.png "$HOME/.local/share/icons/hicolor/256x256/apps/lightread.png"
fi
desktop-file-validate "$HOME/.local/share/applications/lightread.desktop" || true
update-desktop-database "$HOME/.local/share/applications" || true