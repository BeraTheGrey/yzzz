#!/usr/bin/env bash
# Linux: builds dist/SwitchLib/SwitchLib
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm --windowed --name SwitchLib switchlib_launcher.py
echo "Built: dist/SwitchLib/SwitchLib"
