#define MyAppName "FreeCleaner"
#define MyAppPublisher "FreeCleaner"
#define MyAppExeName "FreeCleaner.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0.0"
#endif
#ifndef MyAppArch
  #define MyAppArch "win64"
#endif
#ifndef MySourceDir
  #define MySourceDir "dist\FreeCleaner"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "dist"
#endif

[Setup]
AppId={{3D6B3E8F-7F21-4A7A-9C0A-F3EE7C1EA001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} ({#MyAppArch})
AppPublisher={#MyAppPublisher}
DefaultDirName={code:GetInstallDir}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
PrivilegesRequired=admin
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-{#MyAppArch}-setup
SetupIconFile=assets\icons\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AlwaysRestart=no
MinVersion=6.1sp1
#if MyAppArch == "win64"
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#else
ArchitecturesAllowed=x86compatible
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
InstallModeFreshTitle=Install FreeCleaner
InstallModeFreshWelcome=Install FreeCleaner
InstallModeFreshDescription=This will install FreeCleaner on this computer.
InstallModeUpdateTitle=Update FreeCleaner
InstallModeUpdateWelcome=Update FreeCleaner
InstallModeUpdateDescription=Setup found an existing FreeCleaner installation and will update it in place.
InstallModeUpdateInfo=Installed version: %1%2New version: {#MyAppVersion}
InstallModeNewInfo=New installation: {#MyAppVersion}
LaunchAfterInstall=Launch FreeCleaner
DesktopShortcut=Create a desktop shortcut
AdditionalShortcuts=Additional shortcuts:

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; GroupDescription: "{cm:AdditionalShortcuts}"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "PRIVACY_POLICY.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\app.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchAfterInstall}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKLM; Subkey: "Software\FreeCleaner"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\FreeCleaner"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\FreeCleaner"; ValueType: string; ValueName: "LastInstallMode"; ValueData: "{code:GetInstallMode}"; Flags: uninsdeletekeyifempty

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\FreeCleaner\Temp"

[Code]
var
  IsUpdateInstall: Boolean;
  ExistingInstallDir: String;
  ExistingVersion: String;

function UninstallKey(): String;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{3D6B3E8F-7F21-4A7A-9C0A-F3EE7C1EA001}_is1';
end;

function ReadInstalledInfoFromRoot(RootKey: Integer): Boolean;
var
  DirValue: String;
  VerValue: String;
  ExeValue: String;
begin
  Result := False;
  if RegQueryStringValue(RootKey, UninstallKey(), 'InstallLocation', DirValue) then
  begin
    if DirValue <> '' then
    begin
      ExistingInstallDir := RemoveBackslash(DirValue);
      Result := True;
    end;
  end;
  if RegQueryStringValue(RootKey, UninstallKey(), 'DisplayIcon', ExeValue) then
  begin
    if (ExistingInstallDir = '') and (ExeValue <> '') then
      ExistingInstallDir := RemoveBackslash(ExtractFileDir(ExeValue));
    Result := True;
  end;
  if RegQueryStringValue(RootKey, UninstallKey(), 'DisplayVersion', VerValue) then
  begin
    ExistingVersion := VerValue;
    Result := True;
  end;
end;

function ReadExistingInstall(): Boolean;
begin
  ExistingInstallDir := '';
  ExistingVersion := '';
  Result := ReadInstalledInfoFromRoot(HKLM);
  if not Result then
    Result := ReadInstalledInfoFromRoot(HKCU);
  if not Result then
  begin
    if FileExists(ExpandConstant('{autopf}\{#MyAppName}\{#MyAppExeName}')) then
    begin
      ExistingInstallDir := ExpandConstant('{autopf}\{#MyAppName}');
      Result := True;
    end;
  end;
  if ExistingVersion = '' then
    ExistingVersion := 'installed copy';
end;

function InitializeSetup(): Boolean;
begin
  IsUpdateInstall := ReadExistingInstall();
  Result := True;
end;

function GetInstallDir(Param: String): String;
begin
  if IsUpdateInstall and (ExistingInstallDir <> '') then
    Result := ExistingInstallDir
  else
    Result := ExpandConstant('{autopf}\{#MyAppName}');
end;

function GetInstallMode(Param: String): String;
begin
  if IsUpdateInstall then
    Result := 'update'
  else
    Result := 'install';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if IsUpdateInstall then
  begin
    if (PageID = wpSelectDir) or (PageID = wpSelectProgramGroup) or (PageID = wpSelectTasks) then
      Result := True;
  end;
end;

procedure InitializeWizard();
begin
  if IsUpdateInstall then
  begin
    WizardForm.Caption := ExpandConstant('{cm:InstallModeUpdateTitle}');
    WizardForm.WelcomeLabel1.Caption := ExpandConstant('{cm:InstallModeUpdateWelcome}');
    WizardForm.WelcomeLabel2.Caption := ExpandConstant('{cm:InstallModeUpdateDescription}');
  end
  else
  begin
    WizardForm.Caption := ExpandConstant('{cm:InstallModeFreshTitle}');
    WizardForm.WelcomeLabel1.Caption := ExpandConstant('{cm:InstallModeFreshWelcome}');
    WizardForm.WelcomeLabel2.Caption := ExpandConstant('{cm:InstallModeFreshDescription}');
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  InfoText: String;
begin
  if CurPageID = wpReady then
  begin
    if IsUpdateInstall then
      InfoText := ExpandConstant('{cm:InstallModeUpdateInfo|' + ExistingVersion + '|#13#10}')
    else
      InfoText := ExpandConstant('{cm:InstallModeNewInfo}');
    WizardForm.ReadyMemo.Lines.Insert(0, '');
    WizardForm.ReadyMemo.Lines.Insert(0, InfoText);
  end;
end;
