; Inno Setup script for the Windows installer. Build after PyInstaller:
;   iscc /DAppVersion=0.1.0 packaging\windows\flextri.iss
; Installs for the current user only (no admin prompt) and adds Start menu and desktop shortcuts.
; The athlete's data lives in %LOCALAPPDATA%\flexTri and is kept on uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7C1E6E52-3F7B-4C55-9C1E-5F3A2E4B9A11}
AppName=flexTri
AppVersion={#AppVersion}
AppPublisher=flexTri
DefaultDirName={localappdata}\Programs\flexTri
DefaultGroupName=flexTri
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=flexTri-{#AppVersion}-windows-setup
SetupIconFile=..\build\flextri.ico
UninstallDisplayIcon={app}\flexTri.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put a flexTri icon on the desktop"; Flags: checkedonce

[Files]
Source: "..\..\dist\flexTri\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\flexTri"; Filename: "{app}\flexTri.exe"
Name: "{userdesktop}\flexTri"; Filename: "{app}\flexTri.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\flexTri.exe"; Description: "Start flexTri now"; Flags: nowait postinstall skipifsilent
