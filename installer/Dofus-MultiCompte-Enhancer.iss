#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "Dofus MultiCompte Enhancer"
#define MyAppPublisher "silverspy"
#define MyAppExeName "runtime\pythonw.exe"
#define MyAppScript "app\dofus_panel.pyw"

[Setup]
AppId={{84766B7E-2D98-4AF1-A1EA-1F6E0AE3F31E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/silverspy/Dofus-MultiCompte-Enhancer
AppSupportURL=https://github.com/silverspy/Dofus-MultiCompte-Enhancer/issues
AppUpdatesURL=https://github.com/silverspy/Dofus-MultiCompte-Enhancer/releases/latest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=Dofus-MultiCompte-Enhancer-Setup
SetupIconFile=..\app\assets\dofus-multicompteenhancer.ico
UninstallDisplayIcon={app}\dofus-multicompteenhancer.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
RestartApplications=no
Uninstallable=yes
#ifdef EnableCodeSigning
SignTool=dmce
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\dist-installed\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\app\assets\dofus-multicompteenhancer.ico"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Remove the legacy PyInstaller runtime before installing the transparent one.
Type: files; Name: "{app}\Dofus-MultiCompte-Enhancer.exe"
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "&quot;{app}\{#MyAppScript}&quot;"; WorkingDir: "{app}\app"; IconFilename: "{app}\dofus-multicompteenhancer.ico"; IconIndex: 0
Name: "{autoprograms}\{#MyAppName}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\dofus-multicompteenhancer.ico"; IconIndex: 0
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "&quot;{app}\{#MyAppScript}&quot;"; WorkingDir: "{app}\app"; IconFilename: "{app}\dofus-multicompteenhancer.ico"; IconIndex: 0; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "&quot;{app}\{#MyAppScript}&quot;"; WorkingDir: "{app}\app"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
