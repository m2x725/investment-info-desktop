param([Parameter(Mandatory=$true)][string]$ExePath)
$ErrorActionPreference = "Stop"
$exe = (Resolve-Path $ExePath).Path
if ([IO.Path]::GetFileName($exe) -ne "RetirementWealth.exe") { throw "Select the packaged RetirementWealth.exe." }
$startup = [Environment]::GetFolderPath("Startup")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $startup "RetirementWealth.lnk"))
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = Split-Path $exe -Parent
$shortcut.Save()
Write-Host "Autostart enabled. Remove RetirementWealth.lnk from the Startup folder to disable."
