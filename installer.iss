; Treydchi -- Inno Setup skripti
; Bu skript build.bat orqali yaratilgan "dist\Treydchi.exe" faylini
; oddiy o'rnatuvchi (Setup.exe) qiladi.
;
; Ishlatish:
;   1) Avval build.bat ni ishga tushirib, dist\Treydchi.exe yaratilganiga
;      ishonch hosil qiling.
;   2) Inno Setup dasturini o'rnating: https://jrsoftware.org/isdl.php
;   3) Ushbu faylni (installer.iss) Inno Setup Compiler bilan oching.
;   4) "Build" -> "Compile" (yoki F9) bosing.
;   5) Natija: Output\Treydchi-Setup.exe

#define MyAppName "Treydchi"
#define MyAppVersion "1.0"
#define MyAppPublisher "Treydchi"
#define MyAppExeName "Treydchi.exe"

[Setup]
AppId={{D6F34A72-9B1C-4D8E-A5F2-7C91B2E64013}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Treydchi-Setup
SetupIconFile=icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Ishchi stolga (Desktop) yorliq yaratish"; GroupDescription: "Qo'shimcha vazifalar:"

[Files]
Source: "dist\Treydchi.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
; cloudflared.exe -- Telegram bot "Mini App" (narx/qoldiq ko'rish ilovasi)
; ishlashi uchun kerak. Agar bu fayl topilmasa ham o'rnatuvchi xatosiz
; yig'iladi (skipifsourcedoesntexist) -- shunda dastur oddiy chat orqali
; narx so'rash bilan baribir ishlayveradi, faqat Mini App tugmasi ishlamaydi.
Source: "cloudflared.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "dist\cloudflared.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName}'ni hoziroq ishga tushirish"; Flags: nowait postinstall skipifsilent
