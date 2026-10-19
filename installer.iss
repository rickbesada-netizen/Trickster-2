; Inno Setup script - builds TricksterSetup.exe (a normal Windows installer).
; Installs for the current user only (no admin prompt) into
; %LocalAppData%\Programs\Trickster, adds Start menu + optional desktop
; shortcut, and registers in Settings > Apps so it uninstalls like any app.
[Setup]
AppId={{7B1E3C52-5A0D-4C57-9B7A-1F2E3D4C5B6A}
AppName=Trickster - Antidetect application
AppVersion={#GetEnv("TRICKSTER_VERSION")}
AppPublisher=Trickster
DefaultDirName={localappdata}\Programs\Trickster
DefaultGroupName=Trickster
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=TricksterSetup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\Trickster.exe
UninstallDisplayName=Trickster - Antidetect application
Compression=lzma2
SolidCompression=yes
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Files]
Source: "dist\Trickster.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Trickster"; Filename: "{app}\Trickster.exe"
Name: "{autodesktop}\Trickster"; Filename: "{app}\Trickster.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Trickster.exe"; Description: "Open Trickster now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The downloaded browser and the log are re-creatable; profiles are kept.
Type: filesandordirs; Name: "{app}\browsers"
Type: files; Name: "{app}\trickster.log"
