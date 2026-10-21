param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$editionRoot = $PSScriptRoot
$parentRoot = Split-Path -Parent $editionRoot
$runtimeRoot = if (Test-Path -LiteralPath (Join-Path $editionRoot 'backend/crawler.py')) { $editionRoot } elseif (Test-Path -LiteralPath (Join-Path $parentRoot 'backend/crawler.py')) { $parentRoot } else { throw 'Missing backend source. Download and extract the complete local helper package first.' }
Set-Location -LiteralPath $runtimeRoot
$cacheRoot = Join-Path $runtimeRoot 'cache/local-fetch'
New-Item -ItemType Directory -Force -Path $cacheRoot,(Join-Path $cacheRoot 'tmp'),(Join-Path $cacheRoot 'pip'),(Join-Path $runtimeRoot 'logs/local-fetch') | Out-Null
$env:TEMP = Join-Path $cacheRoot 'tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $cacheRoot 'pip'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$pythonPath = Join-Path $runtimeRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    $bootstrap = if ($pythonCommand) { $pythonCommand.Source } else { Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' }
    if (!(Test-Path -LiteralPath $bootstrap)) { throw 'Python 3.11+ is required. Install Python and rerun this script.' }
    & $bootstrap -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
    & $bootstrap -m venv (Join-Path $runtimeRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project Python environment.' }
}
& $pythonPath -c "import importlib.util,sys; sys.exit(0 if sys.version_info >= (3,11) and all(importlib.util.find_spec(x) for x in ('fastapi','uvicorn','httpx','bs4')) else 1)"
if ($LASTEXITCODE -ne 0) {
    & $pythonPath -m pip install -r (Join-Path $editionRoot 'requirements-local.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your network and rerun this script.' }
}
try { $running = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/fetch-api/health' -TimeoutSec 2 } catch { $running = $null }
if ($running -and ($running.app -ne 'link-atlas-fetch' -or $running.mode -ne 'local' -or $running.storage -ne 'none')) { throw 'Port 8787 is occupied by another service. Do not stop an unknown process.' }
if (!$running) {
    $entry = Join-Path $editionRoot 'server/local.py'
    $serverProcess = Start-Process -FilePath $pythonPath -ArgumentList ('"' + $entry + '"') -WorkingDirectory $runtimeRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeRoot 'logs/local-fetch/out.log') -RedirectStandardError (Join-Path $runtimeRoot 'logs/local-fetch/error.log') -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 300
        if ($serverProcess.HasExited) { throw 'Local helper exited. See logs/local-fetch/error.log.' }
        try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/fetch-api/health' -TimeoutSec 1; if ($health.app -eq 'link-atlas-fetch' -and $health.mode -eq 'local') { $ready = $true; break } } catch {}
    }
    if (!$ready) { throw 'The local helper did not become ready. See logs/local-fetch/error.log.' }
}
if (!$NoBrowser) { Start-Process 'https://dian-wa.github.io/link-atlas/' }
Write-Host 'Local fetch helper is running at http://127.0.0.1:8787 (no database).'
Write-Host 'Open https://dian-wa.github.io/link-atlas/ and click the local connection button.'
Write-Host 'Allow local network access in Chrome or Edge when prompted. Keep this helper running.'
Write-Host 'To stop only this helper, run stop-local-fetch.cmd.'
