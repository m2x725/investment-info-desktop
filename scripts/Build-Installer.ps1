param([string]$Version = '')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$sourceVersion = (& .\.venv\Scripts\python.exe -c "from backend.desktop import APP_VERSION; print(APP_VERSION)").Trim()
if (!$Version) { $Version = $sourceVersion }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid version.' }
if ($LASTEXITCODE -ne 0 -or $Version -ne $sourceVersion) { throw "Installer version $Version differs from application version $sourceVersion." }
$iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
if (!(Test-Path $iscc)) { throw 'Install Inno Setup 6 from https://jrsoftware.org/isdl.php first.' }
New-Item -ItemType Directory -Path dist/prerequisites -Force | Out-Null
$bootstrapper = Join-Path $PWD 'dist/prerequisites/MicrosoftEdgeWebview2Setup.exe'
Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $bootstrapper
$signature = Get-AuthenticodeSignature $bootstrapper
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'WebView2 bootstrapper signature verification failed.' }
& $iscc "/DAppVersion=$Version" packaging/InvestmentInfo.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$files = @((Get-ChildItem "dist/InvestmentInfo-$Version-Setup.exe"), (Get-Item dist/RetirementWealth-Windows.zip))
$lines = $files | ForEach-Object { "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)" }
$lines | Set-Content dist/SHA256SUMS.txt -Encoding ascii
Write-Host 'Installer and checksums created; unsigned preview requires Windows acceptance.'
