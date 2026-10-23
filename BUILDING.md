# Build notes

- `build.bat` is an initial PyInstaller recipe for Windows, not a guaranteed reproducible build.
- Run it on Windows, not macOS.
- If the executable fails because a plugin, resource, or dynamic import is missing, adjust the PyInstaller command and test again.
- `installer.iss` expects `dist\Treydchi.exe` and `icon.ico`.
- `cloudflared.exe` is optional and is not bundled in this repository. Only obtain it from the official Cloudflare release page and review its license and security implications before bundling it.
- Never commit generated executables, user settings, databases, or credentials.
