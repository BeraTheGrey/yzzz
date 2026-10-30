@echo off
rem Windows: builds dist\SwitchLib\SwitchLib.exe
cd /d "%~dp0\.."
py -m pip install -r requirements.txt pyinstaller || exit /b 1
py -m PyInstaller --noconfirm --windowed --name SwitchLib switchlib_launcher.py || exit /b 1
echo Built: dist\SwitchLib\SwitchLib.exe
