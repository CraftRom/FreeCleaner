#define MyAppName "FreeCleaner"
#define MyAppPublisher "FreeCleaner"
#define MyAppExeName "FreeCleaner.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0.0"
#endif
#ifndef MyAppArch
  #define MyAppArch "win64"
#endif
#ifndef MySourceExe
  #define MySourceExe "dist\\FreeCleaner.exe"
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
DefaultDirName={autopf}\{#MyAppName}
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

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#MySourceExe}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "PRIVACY_POLICY.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\icons\app.ico"; DestDir: "{app}\assets\icons"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\app.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icons\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\FreeCleaner\Temp"
