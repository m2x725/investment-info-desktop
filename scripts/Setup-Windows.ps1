$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Install Python 3.12 and its py launcher first." }
& .\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
Push-Location frontend
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
} finally { Pop-Location }
Write-Host "Ready. Double-click Start.bat to open the application."
