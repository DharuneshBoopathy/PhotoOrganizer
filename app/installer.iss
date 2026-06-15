; ====================================================================
;  Photo Organizer — Inno Setup script
;
;  Build with:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;  or via build.bat installer
;
;  Output:
;     installer\Output\PhotoOrganizer-Setup.exe
;
;  Design notes:
;    * PER-USER install by default (no admin rights). Users can opt
;      to install for all users via the privilege override dialog.
;    * Dist contents are folder-mode (~425 MB) — installs into
;      {autopf}\PhotoOrganizer or {localappdata}\Programs\...
;    * App data (logs, prefs, models cache) lives under %LOCALAPPDATA%
;      and is preserved across uninstall (so reinstall keeps state).
;    * `cache/` is the only folder we auto-clean on uninstall.
; ====================================================================

#define AppName        "Photo Organizer"
#define AppShort       "PhotoOrganizer"
#define AppPublisher   "Photo Organizer Project"
#define AppExeName     "PhotoOrganizer.exe"
#define AppId          "{{D9F8E1F0-3B6E-4C2C-9B36-7A9B2F7C1D4A}"
#define AppHomepage    "https://github.com/DharuneshBoopathy/PhotoOrganizer"

; Version is read from src\version.py at compile time
#define FileHandle = FileOpen("src\version.py")
#define VersionLine = ""
#expr SetupSetting("__verseek", "")
; Brute-force scan for __version__ = "x.y.z"
#define VERLINE = ""
#define i 0
#define DONE 0
#define ScanLine
#sub ScanLine
  #define VERLINE FileRead(FileHandle)
  #if VERLINE != ""
    #if (Pos("__version__", VERLINE) > 0) && (DONE == 0)
      #define DONE 1
      #define AppVersion Trim(Copy(VERLINE, Pos('"', VERLINE)+1, RPos('"', VERLINE) - Pos('"', VERLINE) - 1))
    #endif
  #endif
#endsub
#for {i = 0; (i < 200) && (!FileEof(FileHandle)) && (DONE == 0); i++} ScanLine
#expr FileClose(FileHandle)
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppHomepage}
AppSupportURL={#AppHomepage}/issues
AppUpdatesURL={#AppHomepage}/releases
AppContact={#AppHomepage}
AppReadmeFile={#AppHomepage}#readme

DefaultDirName={autopf}\{#AppShort}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableWelcomePage=no
DisableReadyPage=no

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline

ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64

; --- Output ---
OutputDir=installer\Output
OutputBaseFilename=PhotoOrganizer-Setup-{#AppVersion}
SetupIconFile=assets\app_icon.ico
WizardStyle=modern
WizardSizePercent=120
ShowLanguageDialog=auto

; --- Compression ---
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; --- Trust / metadata ---
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
LicenseFile=LICENSE

; Keep original timestamps so SmartScreen reputation can build
TimeStampsInUTC=yes

; SignTool=signtool $f      ; <-- enable when you have a code-signing cert
; SignedUninstaller=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";  Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "quicklaunchicon"; Description: "Create a &Quick Launch shortcut"; \
    GroupDescription: "Additional shortcuts:"; Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
Source: "dist\PhotoOrganizer\*"; \
    DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs solidbreak
Source: "README.md";    DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "LICENSE";      DestDir: "{app}"; Flags: ignoreversion
Source: "CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}";        Filename: "{app}\{#AppExeName}"; \
    IconFilename: "{app}\{#AppExeName}"; Comment: "Local-first photo organizer"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon; IconFilename: "{app}\{#AppExeName}"
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only the cache. Logs, prefs, and the models cache are preserved
; so reinstalls don't have to re-download buffalo_l (~280 MB).
Type: filesandordirs; Name: "{localappdata}\PhotoOrganizer\cache"

[Registry]
; Friendly name in Add/Remove Programs ("Apps & Features")
Root: HKCU; Subkey: "Software\{#AppPublisher}\{#AppShort}"; \
    ValueType: string; ValueName: "Version"; ValueData: "{#AppVersion}"; \
    Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#AppPublisher}\{#AppShort}"; \
    ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; \
    Flags: uninsdeletevalue

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  // Future: VC++ Redistributable check, .NET runtime check, etc.
end;

procedure InitializeWizard();
begin
  // Pre-empt the AV-paranoia question users may have
  WizardForm.DiskSpaceLabel.Caption :=
    'This app installs ~450 MB. All processing is local — '
    'no internet connection is required after install.';
end;

function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit AppId}_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  sUnInstallString: String;
begin
  // Auto-uninstall the previous version (silent) on upgrade
  if (CurStep = ssInstall) and IsUpgrade() then
  begin
    sUnInstallString := GetUninstallString();
    sUnInstallString := RemoveQuotes(sUnInstallString);
    Exec(sUnInstallString, '/SILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
