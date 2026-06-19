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
Name: "desktopicon"; Description: "{code:GetDesktopShortcutText}"; GroupDescription: "{code:GetAdditionalShortcutsText}"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "PRIVACY_POLICY.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\app.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{code:GetLaunchAfterInstallText}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKLM; Subkey: "Software\FreeCleaner"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\FreeCleaner"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\FreeCleaner"; ValueType: string; ValueName: "LastInstallMode"; ValueData: "{code:GetInstallMode}"; Flags: uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\FreeCleaner"; ValueType: string; ValueName: "DefaultLanguage"; ValueData: "{code:GetSelectedLanguage}"; Flags: uninsdeletekeyifempty

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\FreeCleaner\Temp"

[Code]
var
  IsUpdateInstall: Boolean;
  ExistingInstallDir: String;
  ExistingVersion: String;
  ExistingLanguagePreference: String;
  SelectedLanguagePreference: String;
  DetectedSystemLanguage: String;
  LanguagePage: TInputOptionWizardPage;


function NormalizeLanguagePreference(Value: String): String;
begin
  Value := Lowercase(Trim(Value));
  if (Value = 'system') or (Value = 'default') or (Value = '') then
    Result := 'auto'
  else if (Value = 'auto') or (Value = 'uk') or (Value = 'en') or (Value = 'de') or (Value = 'es') or (Value = 'pl') then
    Result := Value
  else
    Result := 'auto';
end;

function LanguageName(Code: String): String;
begin
  Code := NormalizeLanguagePreference(Code);
  if Code = 'uk' then
    Result := 'Українська'
  else if Code = 'de' then
    Result := 'Deutsch'
  else if Code = 'es' then
    Result := 'Español'
  else if Code = 'pl' then
    Result := 'Polski'
  else if Code = 'en' then
    Result := 'English'
  else if DetectedSystemLanguage <> '' then
    Result := 'System — ' + LanguageName(DetectedSystemLanguage)
  else
    Result := 'System';
end;

function DetectSystemLanguage(): String;
var
  Primary: Integer;
begin
  Result := 'en';
  try
    Primary := GetUILanguage() and $3FF;
    if Primary = $22 then
      Result := 'uk'
    else if Primary = $07 then
      Result := 'de'
    else if Primary = $0A then
      Result := 'es'
    else if Primary = $15 then
      Result := 'pl'
    else if Primary = $09 then
      Result := 'en'
    else
      Result := 'en';
  except
    Result := 'en';
  end;
end;

function EffectiveInstallerLanguage(): String;
begin
  if NormalizeLanguagePreference(SelectedLanguagePreference) = 'auto' then
    Result := DetectSystemLanguage()
  else
    Result := NormalizeLanguagePreference(SelectedLanguagePreference);
end;

function UiText(Key: String): String;
var
  L: String;
begin
  L := EffectiveInstallerLanguage();

  if Key = 'language_title' then
  begin
    if L = 'uk' then Result := 'Мова встановлення'
    else if L = 'de' then Result := 'Installationssprache'
    else if L = 'es' then Result := 'Idioma de instalación'
    else if L = 'pl' then Result := 'Język instalacji'
    else Result := 'Setup language';
  end
  else if Key = 'language_desc' then
  begin
    if L = 'uk' then Result := 'Оберіть мову FreeCleaner'
    else if L = 'de' then Result := 'Wählen Sie die Sprache von FreeCleaner'
    else if L = 'es' then Result := 'Elige el idioma de FreeCleaner'
    else if L = 'pl' then Result := 'Wybierz język FreeCleaner'
    else Result := 'Choose the FreeCleaner language';
  end
  else if Key = 'language_sub' then
  begin
    if L = 'uk' then Result := 'Ця мова буде збережена як стандартна для програми. Під час оновлення використовується вже вибрана мова, якщо її можна знайти.'
    else if L = 'de' then Result := 'Diese Sprache wird als Standard für die App gespeichert. Bei einem Update wird die vorhandene Sprache übernommen, wenn sie gefunden wird.'
    else if L = 'es' then Result := 'Este idioma se guardará como predeterminado de la aplicación. Al actualizar, se usará el idioma existente si se encuentra.'
    else if L = 'pl' then Result := 'Ten język zostanie zapisany jako domyślny dla aplikacji. Podczas aktualizacji zostanie użyty istniejący język, jeśli można go odczytać.'
    else Result := 'This language will be saved as the app default. During updates, Setup uses the existing language when it can read it.';
  end
  else if Key = 'fresh_title' then
  begin
    if L = 'uk' then Result := 'Встановлення FreeCleaner'
    else if L = 'de' then Result := 'FreeCleaner installieren'
    else if L = 'es' then Result := 'Instalar FreeCleaner'
    else if L = 'pl' then Result := 'Instalacja FreeCleaner'
    else Result := 'Install FreeCleaner';
  end
  else if Key = 'fresh_desc' then
  begin
    if L = 'uk' then Result := 'FreeCleaner буде встановлено на цей комп’ютер.'
    else if L = 'de' then Result := 'FreeCleaner wird auf diesem Computer installiert.'
    else if L = 'es' then Result := 'FreeCleaner se instalará en este equipo.'
    else if L = 'pl' then Result := 'FreeCleaner zostanie zainstalowany na tym komputerze.'
    else Result := 'FreeCleaner will be installed on this computer.';
  end
  else if Key = 'update_title' then
  begin
    if L = 'uk' then Result := 'Оновлення FreeCleaner'
    else if L = 'de' then Result := 'FreeCleaner aktualisieren'
    else if L = 'es' then Result := 'Actualizar FreeCleaner'
    else if L = 'pl' then Result := 'Aktualizacja FreeCleaner'
    else Result := 'Update FreeCleaner';
  end
  else if Key = 'update_desc' then
  begin
    if L = 'uk' then Result := 'Знайдено встановлений FreeCleaner. Інсталятор оновить його у цій самій папці.'
    else if L = 'de' then Result := 'Eine vorhandene FreeCleaner-Installation wurde gefunden und wird im selben Ordner aktualisiert.'
    else if L = 'es' then Result := 'Se encontró una instalación de FreeCleaner y se actualizará en la misma carpeta.'
    else if L = 'pl' then Result := 'Znaleziono zainstalowany FreeCleaner. Instalator zaktualizuje go w tym samym folderze.'
    else Result := 'An existing FreeCleaner installation was found and will be updated in the same folder.';
  end
  else if Key = 'launch' then
  begin
    if L = 'uk' then Result := 'Запустити FreeCleaner'
    else if L = 'de' then Result := 'FreeCleaner starten'
    else if L = 'es' then Result := 'Iniciar FreeCleaner'
    else if L = 'pl' then Result := 'Uruchom FreeCleaner'
    else Result := 'Launch FreeCleaner';
  end
  else if Key = 'desktop' then
  begin
    if L = 'uk' then Result := 'Створити ярлик на робочому столі'
    else if L = 'de' then Result := 'Desktop-Verknüpfung erstellen'
    else if L = 'es' then Result := 'Crear acceso directo en el escritorio'
    else if L = 'pl' then Result := 'Utwórz skrót na pulpicie'
    else Result := 'Create a desktop shortcut';
  end
  else if Key = 'shortcuts' then
  begin
    if L = 'uk' then Result := 'Додаткові ярлики:'
    else if L = 'de' then Result := 'Zusätzliche Verknüpfungen:'
    else if L = 'es' then Result := 'Accesos directos adicionales:'
    else if L = 'pl' then Result := 'Dodatkowe skróty:'
    else Result := 'Additional shortcuts:';
  end
  else if Key = 'ready_new' then
  begin
    if L = 'uk' then Result := 'Нове встановлення: {#MyAppVersion}'
    else if L = 'de' then Result := 'Neue Installation: {#MyAppVersion}'
    else if L = 'es' then Result := 'Instalación nueva: {#MyAppVersion}'
    else if L = 'pl' then Result := 'Nowa instalacja: {#MyAppVersion}'
    else Result := 'New installation: {#MyAppVersion}';
  end
  else
    Result := Key;
end;

function ExtractJsonStringValue(Content: String; Key: String): String;
var
  KeyToken: String;
  P, C, Q1, Q2: Integer;
begin
  Result := '';
  KeyToken := '"' + Key + '"';
  P := Pos(KeyToken, Content);
  if P <= 0 then Exit;
  C := P + Length(KeyToken);
  while (C <= Length(Content)) and (Copy(Content, C, 1) <> ':') do C := C + 1;
  if C > Length(Content) then Exit;
  Q1 := C + 1;
  while (Q1 <= Length(Content)) and (Copy(Content, Q1, 1) <> '"') do Q1 := Q1 + 1;
  if Q1 > Length(Content) then Exit;
  Q2 := Q1 + 1;
  while (Q2 <= Length(Content)) and (Copy(Content, Q2, 1) <> '"') do Q2 := Q2 + 1;
  if Q2 > Length(Content) then Exit;
  Result := Copy(Content, Q1 + 1, Q2 - Q1 - 1);
end;

function ReadLanguageFromConfigFile(Path: String): String;
var
  Content: String;
begin
  Result := '';
  if FileExists(Path) then
  begin
    if LoadStringFromFile(Path, Content) then
      Result := NormalizeLanguagePreference(ExtractJsonStringValue(Content, 'language'));
  end;
end;

function ReadExistingLanguagePreference(): String;
begin
  Result := '';
  { During updates prefer config from the installed app folder, then user config. }
  if IsUpdateInstall and (ExistingInstallDir <> '') then
    Result := ReadLanguageFromConfigFile(AddBackslash(ExistingInstallDir) + 'config.json');
  if Result = '' then
    Result := ReadLanguageFromConfigFile(ExpandConstant('{localappdata}\FreeCleaner\config.json'));
  if Result = '' then
    Result := 'auto';
end;

function ReplaceOrAddJsonLanguage(Content: String; Value: String): String;
var
  KeyToken: String;
  P, C, Q1, Q2, CloseBrace: Integer;
  Body: String;
begin
  Value := NormalizeLanguagePreference(Value);
  Content := Trim(Content);
  KeyToken := '"language"';
  P := Pos(KeyToken, Content);
  if P > 0 then
  begin
    C := P + Length(KeyToken);
    while (C <= Length(Content)) and (Copy(Content, C, 1) <> ':') do C := C + 1;
    Q1 := C + 1;
    while (Q1 <= Length(Content)) and (Copy(Content, Q1, 1) <> '"') do Q1 := Q1 + 1;
    Q2 := Q1 + 1;
    while (Q2 <= Length(Content)) and (Copy(Content, Q2, 1) <> '"') do Q2 := Q2 + 1;
    if (Q1 <= Length(Content)) and (Q2 <= Length(Content)) then
    begin
      Result := Copy(Content, 1, Q1) + Value + Copy(Content, Q2, Length(Content) - Q2 + 1);
      Exit;
    end;
  end;

  if (Length(Content) < 2) or (Copy(Content, 1, 1) <> '{') then
  begin
    Result := '{'#13#10'  "language": "' + Value + '"'#13#10'}';
    Exit;
  end;

  CloseBrace := Length(Content);
  while (CloseBrace > 0) and (Copy(Content, CloseBrace, 1) <> '}') do CloseBrace := CloseBrace - 1;
  if CloseBrace <= 0 then
  begin
    Result := '{'#13#10'  "language": "' + Value + '"'#13#10'}';
    Exit;
  end;

  Body := Trim(Copy(Content, 2, CloseBrace - 2));
  if Body = '' then
    Result := '{'#13#10'  "language": "' + Value + '"'#13#10'}'
  else
    Result := '{'#13#10'  "language": "' + Value + '",'#13#10 + Body + #13#10'}';
end;

procedure SaveSelectedLanguageConfig();
var
  ConfigDir: String;
  ConfigPath: String;
  Content: String;
begin
  ConfigDir := ExpandConstant('{localappdata}\FreeCleaner');
  ConfigPath := AddBackslash(ConfigDir) + 'config.json';
  ForceDirectories(ConfigDir);
  if not LoadStringFromFile(ConfigPath, Content) then
    Content := '';
  Content := ReplaceOrAddJsonLanguage(Content, SelectedLanguagePreference);
  SaveStringToFile(ConfigPath, Content, False);
end;

procedure ApplyInstallerLanguageToWizard();
begin
  if IsUpdateInstall then
  begin
    WizardForm.Caption := UiText('update_title');
    WizardForm.WelcomeLabel1.Caption := UiText('update_title');
    WizardForm.WelcomeLabel2.Caption := UiText('update_desc');
  end
  else
  begin
    WizardForm.Caption := UiText('fresh_title');
    WizardForm.WelcomeLabel1.Caption := UiText('fresh_title');
    WizardForm.WelcomeLabel2.Caption := UiText('fresh_desc');
  end;
end;

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
  DetectedSystemLanguage := DetectSystemLanguage();
  ExistingLanguagePreference := ReadExistingLanguagePreference();
  SelectedLanguagePreference := ExistingLanguagePreference;
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

function GetSelectedLanguage(Param: String): String;
begin
  Result := NormalizeLanguagePreference(SelectedLanguagePreference);
end;

function GetLaunchAfterInstallText(Param: String): String;
begin
  Result := UiText('launch');
end;

function GetDesktopShortcutText(Param: String): String;
begin
  Result := UiText('desktop');
end;

function GetAdditionalShortcutsText(Param: String): String;
begin
  Result := UiText('shortcuts');
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
  ApplyInstallerLanguageToWizard();
  LanguagePage := CreateInputOptionPage(
    wpWelcome,
    UiText('language_title'),
    UiText('language_desc'),
    UiText('language_sub'),
    True,
    False
  );
  LanguagePage.Add(LanguageName('auto'));
  LanguagePage.Add(LanguageName('uk'));
  LanguagePage.Add(LanguageName('en'));
  LanguagePage.Add(LanguageName('de'));
  LanguagePage.Add(LanguageName('es'));
  LanguagePage.Add(LanguageName('pl'));

  SelectedLanguagePreference := NormalizeLanguagePreference(SelectedLanguagePreference);
  if SelectedLanguagePreference = 'uk' then LanguagePage.SelectedValueIndex := 1
  else if SelectedLanguagePreference = 'en' then LanguagePage.SelectedValueIndex := 2
  else if SelectedLanguagePreference = 'de' then LanguagePage.SelectedValueIndex := 3
  else if SelectedLanguagePreference = 'es' then LanguagePage.SelectedValueIndex := 4
  else if SelectedLanguagePreference = 'pl' then LanguagePage.SelectedValueIndex := 5
  else LanguagePage.SelectedValueIndex := 0;
end;


function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = LanguagePage.ID then
  begin
    case LanguagePage.SelectedValueIndex of
      1: SelectedLanguagePreference := 'uk';
      2: SelectedLanguagePreference := 'en';
      3: SelectedLanguagePreference := 'de';
      4: SelectedLanguagePreference := 'es';
      5: SelectedLanguagePreference := 'pl';
    else
      SelectedLanguagePreference := 'auto';
    end;
    ApplyInstallerLanguageToWizard();
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveSelectedLanguageConfig();
end;

procedure CurPageChanged(CurPageID: Integer);
var
  InfoText: String;
begin
  if CurPageID = wpReady then
  begin
    if IsUpdateInstall then
      InfoText := UiText('update_title') + ': ' + ExistingVersion + ' → {#MyAppVersion}'
    else
      InfoText := UiText('ready_new');
    InfoText := InfoText + #13#10 + UiText('language_title') + ': ' + LanguageName(SelectedLanguagePreference);
    WizardForm.ReadyMemo.Lines.Insert(0, '');
    WizardForm.ReadyMemo.Lines.Insert(0, InfoText);
  end;
end;
