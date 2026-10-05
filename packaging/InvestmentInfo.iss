#ifndef AppVersion
#define AppVersion "0.1.0"
#endif
[Setup]
AppId={{C28D77AD-7997-4051-AB22-31F580E03B6C}
AppName=投资信息台
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\InvestmentInfo
DefaultGroupName=投资信息台
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=InvestmentInfo-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=no
AppMutex=Local\RetirementWealthDesktop
SetupMutex=Local\RetirementWealthSetup
UninstallDisplayName=投资信息台
UninstallDisplayIcon={app}\RetirementWealth.exe
[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl,Chinese.isl"
[Tasks]
Name: "autostart"; Description: "登录电脑后自动运行"; Flags: unchecked
[Files]
Source: "..\dist\RetirementWealth\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\third-party-notices\*"; DestDir: "{app}\third-party-notices"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\OPEN_SOURCE_REVIEW.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\WINDOWS_INSTALL.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\prerequisites\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy
[Icons]
Name: "{userdesktop}\投资信息台"; Filename: "{app}\RetirementWealth.exe"
Name: "{userprograms}\投资信息台"; Filename: "{app}\RetirementWealth.exe"
Name: "{userstartup}\投资信息台"; Filename: "{app}\RetirementWealth.exe"; Tasks: autostart
[Run]
Filename: "{app}\RetirementWealth.exe"; Description: "打开投资信息台"; Flags: nowait postinstall skipifsilent
[Code]
function HasWebView2: Boolean;
var Version: String;
begin
  Result := (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
  if not Result then
    Result := (RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer; DataDir, Database, Backup: String;
begin
  Result := '';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "if (Get-Process -Name RetirementWealth -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"',
    '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
    Result := '无法检查旧版本运行状态，请先退出软件后重试。'; exit;
  end;
  if ExitCode <> 0 then begin
    Result := '投资信息台仍在运行。请从托盘完全退出后重试。'; exit;
  end;
  if not HasWebView2 then begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
      Result := '无法启动 Microsoft WebView2 安装程序。请联网后重试。'; exit;
    end;
    if not HasWebView2 then begin
      Result := 'Microsoft WebView2 未就绪。请检查网络并安装运行时后重试。'; exit;
    end;
  end;
  DataDir := ExpandConstant('{localappdata}\RetirementWealth');
  Database := DataDir + '\portfolio.db';
  if FileExists(Database) then begin
    Backup := DataDir + '\backups';
    if not ForceDirectories(Backup) then begin Result := '无法创建升级备份目录。'; exit; end;
    Backup := Backup + '\before-setup-' + GetDateTimeString('yyyymmdd-hhnnss', '-', ':') + '.db';
    if not FileCopy(Database, Backup, True) then Result := '数据库备份失败，请检查磁盘空间或权限。';
  end;
end;
