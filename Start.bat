@echo off
cd /d "%~dp0"
if exist "dist\RetirementWealth\RetirementWealth.exe" (
  start "" "dist\RetirementWealth\RetirementWealth.exe"
) else (
  if not exist ".venv\Scripts\python.exe" (
    echo Please run scripts\Setup-Windows.ps1 first.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" run.py
)
