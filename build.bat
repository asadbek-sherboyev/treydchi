@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Checking Python...
python --version
if errorlevel 1 (
  echo Python was not found. Install Python and enable "Add Python to PATH".
  exit /b 1
)

echo [2/4] Installing application dependencies...
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python -m pip install pyinstaller
if errorlevel 1 exit /b 1

echo [3/4] Building Treydchi.exe...
python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name Treydchi ^
  --icon icon.ico ^
  --collect-all qfluentwidgets ^
  --collect-all PySide6 ^
  --hidden-import PySide6.QtCharts ^
  dokon_gui.py
if errorlevel 1 (
  echo Build failed. Review the PyInstaller output above and add any missing data/imports.
  exit /b 1
)

echo [4/4] Build finished. Output: dist\Treydchi.exe
echo Test this executable on a clean Windows machine before distributing it.
endlocal
