; RTE Hosting branded Windows installer (Inno Setup 6)
#define MyAppName "RTE Hosting Server Manager"
#define MyAppVersion "0.2.0"
#define MyAppExeName "RTEHosting.exe"
[Setup]
AppId={{2C2EE05B-9B35-4B2B-8B57-126C2259E874}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=RTE Hosting
DefaultDirName={localappdata}\Programs\RTE Hosting
DefaultGroupName=RTE Hosting
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=RTEHosting-Setup-v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile=rte-hosting.ico
WizardImageFile=wizard-large.bmp
WizardSmallImageFile=wizard-small.bmp
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
MinVersion=10.0.17763
CloseApplications=force
RestartApplications=yes
ChangesAssociations=no
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\RTEHosting\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\RTE Hosting Control Center"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\RTE Hosting Control Center"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch RTE Hosting Control Center"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Runtime data is deliberately never removed automatically; world backups and
; account records should be retained until the administrator removes them.
Type: files; Name: "{app}\rte-console.log"
