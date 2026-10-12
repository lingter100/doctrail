param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $env:PYTHONUTF8 = '1'
    uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Python setup failed.' }
    Push-Location (Join-Path $projectRoot 'web')
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'Web setup failed.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Web build failed.' }
    } finally { Pop-Location }
    uv run uvicorn doctrail.app:app --host 127.0.0.1 --port $Port
} finally { Pop-Location }
