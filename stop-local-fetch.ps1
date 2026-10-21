$ErrorActionPreference = 'Stop'
$editionRoot = $PSScriptRoot
$parentRoot = Split-Path -Parent $editionRoot
$runtimeRoot = if (Test-Path -LiteralPath (Join-Path $editionRoot 'backend/crawler.py')) { $editionRoot } else { $parentRoot }
try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/fetch-api/health' -TimeoutSec 2 } catch { Write-Host 'Local helper is not running.'; exit 0 }
if ($health.app -ne 'link-atlas-fetch' -or $health.mode -ne 'local' -or $health.storage -ne 'none') { throw 'Port 8787 belongs to another service. Nothing was stopped.' }
$controlPath = Join-Path $runtimeRoot 'cache/local-fetch/control.json'
if (!(Test-Path -LiteralPath $controlPath)) { throw 'Missing local control file. Nothing was stopped.' }
$control = Get-Content -LiteralPath $controlPath -Raw | ConvertFrom-Json
$headers = @{ 'X-Atlas-Control' = $control.token; 'Origin' = 'http://127.0.0.1:8787' }
$null = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8787/fetch-api/control/stop' -Headers $headers -TimeoutSec 3
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 300
    try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/fetch-api/health' -TimeoutSec 1 } catch { Write-Host 'Local fetch helper stopped. Browser data and tasks are retained.'; exit 0 }
}
throw 'The helper is still finishing an active request. Wait a moment and rerun stop-local-fetch.cmd.'
