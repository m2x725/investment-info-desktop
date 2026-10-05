$ErrorActionPreference = 'Stop'
$testDir = Join-Path $env:RUNNER_TEMP ('wealth-smoke-' + [Guid]::NewGuid())
if (!$env:RUNNER_TEMP) { $testDir = Join-Path $env:TEMP ('wealth-smoke-' + [Guid]::NewGuid()) }
$oldData = $env:WEALTH_DATA_DIR
$env:WEALTH_DATA_DIR = $testDir
$process = $null
try {
    $process = Start-Process -FilePath (Resolve-Path 'dist/RetirementWealth/RetirementWealth.exe') -ArgumentList '--headless','--port','8876' -PassThru
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if ($process.HasExited) { throw "Packaged backend exited: $($process.ExitCode)" }
        try {
            $response = Invoke-WebRequest 'http://127.0.0.1:8876/' -TimeoutSec 2
            if ($response.StatusCode -eq 200 -and $response.Content -match '<div id="root">') { $ready = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (!$ready) { throw 'Packaged frontend did not become ready.' }
    Write-Host 'Packaged backend and frontend smoke passed; native GUI and tray still require manual acceptance.'
} finally {
    if ($process -and !$process.HasExited) { Stop-Process -Id $process.Id -Force }
    $env:WEALTH_DATA_DIR = $oldData
}
