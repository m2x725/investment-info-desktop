$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path frontend\dist\index.html)) { throw "Run Setup-Windows.ps1 first." }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name RetirementWealth --add-data "frontend/dist;frontend/dist" --collect-all webview --hidden-import webview.platforms.winforms --hidden-import webview.platforms.edgechromium --collect-all keyring --hidden-import keyring.backends.Windows --collect-all pystray --collect-all openpyxl --collect-all pdfplumber --collect-all pypdfium2 --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all akshare --collect-all riskfolio --collect-all futu --collect-all cvxpy --collect-all clarabel --collect-all scipy --collect-all statsmodels --copy-metadata riskfolio-lib --copy-metadata akshare run.py
if ($LASTEXITCODE -ne 0) { throw "Windows build failed." }
& .\.venv\Scripts\python.exe scripts\Collect-Notices.py
if ($LASTEXITCODE -ne 0) { throw "Licence notice collection failed." }
Copy-Item scripts\Restore-Backup.ps1 dist\Restore-Backup.ps1 -Force
Copy-Item docs\OPEN_SOURCE_REVIEW.md dist\OPEN_SOURCE_REVIEW.md -Force
Copy-Item scripts\Install-Windows.ps1 dist\Install-Windows.ps1 -Force
Copy-Item scripts\Install.bat dist\Install.bat -Force
Copy-Item scripts\Enable-Autostart.ps1 dist\Enable-Autostart.ps1 -Force
Compress-Archive -Path dist\RetirementWealth,dist\Install-Windows.ps1,dist\Install.bat,dist\Enable-Autostart.ps1,dist\Restore-Backup.ps1,dist\OPEN_SOURCE_REVIEW.md,dist\third-party-notices -DestinationPath dist\RetirementWealth-Windows.zip -Force
Write-Host "Build created. Test this ZIP on the target Windows computer before delivery."
