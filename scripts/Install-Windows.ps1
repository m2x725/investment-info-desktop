$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "RetirementWealth"
if (!(Test-Path (Join-Path $source "RetirementWealth.exe"))) {
  throw "Extract the complete release ZIP first. Do not run this file from the source repository."
}
if (Get-Process -Name RetirementWealth -ErrorAction SilentlyContinue) {
  throw "Exit the existing application from its tray menu, then run Install.bat again."
}
$root = Join-Path $env:LOCALAPPDATA "RetirementWealth"
New-Item -ItemType Directory -Force -Path $root | Out-Null
$db = Join-Path $root "portfolio.db"
if (Test-Path $db) {
  $backup = Join-Path $root "backups"
  New-Item -ItemType Directory -Force -Path $backup | Out-Null
  Copy-Item $db (Join-Path $backup ("before-install-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".db"))
}
$release = Join-Path $root ("releases\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $release | Out-Null
Copy-Item -Recurse $source (Join-Path $release "RetirementWealth")
$exe = Join-Path $release "RetirementWealth\RetirementWealth.exe"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "RetirementWealth.lnk"))
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = Split-Path $exe -Parent
$shortcut.Save()
Write-Host "Installed for this user. Your database and saved credentials are preserved."
Write-Host "Open RetirementWealth from the desktop shortcut."
Start-Process $exe
