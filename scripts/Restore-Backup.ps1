param([Parameter(Mandatory=$true)][string]$BackupPath,[Parameter(Mandatory=$true)][string]$ExePath)
$ErrorActionPreference = 'Stop'
if (Get-Process -Name RetirementWealth -ErrorAction SilentlyContinue) { throw 'Exit the application from the tray first.' }
if (!(Test-Path $BackupPath) -or !(Test-Path $ExePath)) { throw 'Choose an existing backup and application executable.' }
& $ExePath --restore-backup (Resolve-Path $BackupPath).Path
if ($LASTEXITCODE -ne 0) { throw 'Restore did not succeed. The application validates the backup before replacing data.' }
