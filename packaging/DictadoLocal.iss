; Per-user setup for Dictado local. The Whisper weights are not included:
; the app downloads them on first launch.

#ifndef MyAppVersion
  #define MyAppVersion "0.2.3"
#endif
#define MyAppVersionInfo MyAppVersion + ".0"
#define MyAppName "Dictado local"
#define MyAppExeName "DictadoLocal.exe"

[Setup]
AppId={{8F3A1C2E-6B47-4D91-9E55-2C7A4B0D6F18}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Molina
AppCopyright=Copyright (C) 2026 Molina
VersionInfoVersion={#MyAppVersionInfo}
VersionInfoProductName={#MyAppName}
DefaultDirName={localappdata}\Programs\dictado-local
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
; Paths stay under the repo root. A ".." segment makes them too long for ISCC.
SourceDir=..
OutputDir=dist
OutputBaseFilename=DictadoLocal-Setup
SetupIconFile=assets\dictado.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UsedUserAreasWarning=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "dist\DictadoLocal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "install.ps1,install.cmd"

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DictadoLocal"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Dictado local"; Flags: nowait postinstall skipifsilent

[Code]
procedure InstallUserConfig();
var
  DestDir: String;
  DestFile: String;
  ExampleFile: String;
begin
  DestDir := ExpandConstant('{userappdata}\dictado-local');
  DestFile := DestDir + '\config.yaml';
  if FileExists(DestFile) then
    Exit;
  if not ForceDirectories(DestDir) then
    Exit;
  ExampleFile := ExpandConstant('{app}\config.example.yaml');
  if not FileExists(ExampleFile) then
    ExampleFile := ExpandConstant('{app}\_internal\config.example.yaml');
  if FileExists(ExampleFile) then
    FileCopy(ExampleFile, DestFile, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InstallUserConfig();
end;
