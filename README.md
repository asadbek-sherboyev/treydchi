# Treydchi

Treydchi is a personal Python desktop application project for small-shop workflows.
The supplied source includes a PySide6 GUI (`dokon_gui.py`) and SQLite-backed
business logic (`dokon_backend.py`).

> **Project status:** personal learning project. The repository documents the
> supplied source; it does not claim that every feature, installer, or platform
> has been independently tested.

## Features represented in the source

- Product and sales records backed by SQLite
- Shop-management GUI built with PySide6 and PySide6-Fluent-Widgets
- Local settings and database persistence
- Optional Telegram integration and Mini App/tunnel-related code
- Reports and other shop workflows implemented in the GUI/backend

Exact feature behavior should be verified by running the application.

## Requirements

- Python 3.10 or newer is recommended; use a Python version supported by the installed PySide6 packages.
- Windows is the primary target for the included Inno Setup installer.
- The code includes some platform-specific integrations. macOS/Linux support may be partial and has not been certified.

## Run from source

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python dokon_gui.py
```

macOS/Linux:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python dokon_gui.py
```

If a dependency or platform-specific feature is unavailable, review the error and
the relevant code before assuming the feature works on that system.

## Build a Windows executable (optional)

The `build.bat` script is a starting point for building a Windows executable
with PyInstaller. Run it on Windows in an environment where dependencies are
installed. A successful build must still be tested on a clean Windows machine.
The Inno Setup script (`installer.iss`) can then package `dist\\Treydchi.exe`.
The installer script and build have not been verified in this environment.

## Author

Asadbek Sherboyev  
GitHub: https://github.com/asadbek-sherboyev
