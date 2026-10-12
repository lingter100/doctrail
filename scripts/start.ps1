param([int]$Port = 8000, [ValidateSet('Java', 'Python')][string]$Backend = 'Java')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    Push-Location (Join-Path $projectRoot 'web')
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'Web setup failed.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Web build failed.' }
    } finally { Pop-Location }
    if ($Backend -eq 'Java') {
        $javaProperties = (& java -XshowSettings:properties -version 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) { throw 'Java 21 is required.' }
        $javaHomeMatch = [regex]::Match($javaProperties, '(?m)^\s*java.home = (.+)$')
        if (-not $javaHomeMatch.Success) { throw 'Cannot resolve the JDK executable.' }
        $javaExecutable = Join-Path $javaHomeMatch.Groups[1].Value.Trim() 'bin/java.exe'
        if (-not (Test-Path -LiteralPath $javaExecutable)) { throw 'JDK executable not found.' }
        & ./server/mvnw.cmd -B -q -f server/pom.xml package '-DskipTests'
        if ($LASTEXITCODE -ne 0) { throw 'Java build failed.' }
        & $javaExecutable -jar server/target/doctrail-server-0.1.0.jar "--server.port=$Port"
    } else {
        $env:PYTHONUTF8 = '1'
        uv sync --frozen
        if ($LASTEXITCODE -ne 0) { throw 'Python reference setup failed.' }
        uv run uvicorn doctrail.app:app --host 127.0.0.1 --port $Port
    }
} finally { Pop-Location }
