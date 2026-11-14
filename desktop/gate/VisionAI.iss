; VISION AI - SRM TRP, gate PC installer (Inno Setup 6).
;
; Build:  desktop\gate\build_gate.ps1   (it calls ISCC when Inno Setup is present)
; Output: dist\installer\VisionAI-Setup.exe
;
; Two rules this script follows:
;   1. Nothing is deleted from %PROGRAMDATA%\VisionAI on uninstall. That folder
;      holds the gate database and its backups: an uninstall must never take the
;      audit trail of a semester with it.
;   2. The portal is installed for localhost only. There is no firewall rule
;      here because nothing on the LAN is supposed to reach this machine; if
;      that ever changes, it is a deliberate decision, not an installer default.

#define MyAppName "VISION AI - SRM TRP"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "SRM TRP Engineering College"
#define MyAppExeName "VisionAI.exe"

[Setup]
AppId={{6F1B7C42-3A5D-4E77-9C1B-8A2E5D4F7B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\VisionAI
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=VisionAI-Setup
SetupIconFile=visionai.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Admin is required for Program Files; the data folder needs PROGRAMDATA write,
; which the installer creates with an explicit ACL below.
PrivilegesRequired=admin
CloseApplications=yes
RestartIfNeededBySystem=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start the portal automatically when Windows starts"; GroupDescription: "Startup:"; Flags: checkedonce

[Files]
Source: "..\..\dist\VisionAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The configuration template is useful on the machine even after setup ran.
Source: "gate.env.example"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; The gate database, its backups and the logs live here, outside the program
; folder, so an upgrade replaces the application and leaves the records alone.
Name: "{commonappdata}\VisionAI"; Permissions: users-modify
Name: "{commonappdata}\VisionAI\data"; Permissions: users-modify
Name: "{commonappdata}\VisionAI\logs"; Permissions: users-modify
Name: "{commonappdata}\VisionAI\backups"; Permissions: users-modify

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\First-time setup"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup"; WorkingDir: "{app}"; Comment: "Create the database and the administrator account"
Name: "{group}\Check this PC"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--check --deep"; WorkingDir: "{app}"; Comment: "Run the preflight: camera, database, detector, OCR"
Name: "{group}\Data folder"; Filename: "{commonappdata}\VisionAI"; Comment: "Database, logs and backups"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
; Autostart starts the portal without opening a browser window on the operator.
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--no-browser"; WorkingDir: "{app}"; Tasks: autostart

[Run]
; The wizard is the one step that cannot be automated: it creates the
; administrator account with a password only the operator knows.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup"; WorkingDir: "{app}"; Description: "Create the database and the administrator account"; Flags: postinstall waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Parameters: "--check"; WorkingDir: "{app}"; Description: "Check this PC now (camera, database, OCR, detector)"; Flags: postinstall nowait skipifsilent
Filename: "{app}\{#MyAppExeName}"; Description: "Start the portal now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#MyAppExeName} /F"; Flags: runhidden skipifdoesntexist

[UninstallDelete]
; Only the program folder. %PROGRAMDATA%\VisionAI is deliberately not listed:
; uninstalling must not destroy the gate's event history.
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDir: String;
begin
  if CurStep = ssPostInstall then
  begin
    DataDir := ExpandConstant('{commonappdata}\VisionAI');
    if not DirExists(DataDir) then
      ForceDirectories(DataDir);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if DirExists(ExpandConstant('{commonappdata}\VisionAI')) then
      MsgBox('The gate database and its logs were kept in:' + #13#10 +
             ExpandConstant('{commonappdata}\VisionAI') + #13#10#13#10 +
             'Delete that folder only if you have finished with the event history.',
             mbInformation, MB_OK);
end;
