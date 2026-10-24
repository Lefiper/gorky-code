$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.env.docker')) {
    $ownerBytes = New-Object byte[] 32
    $appBytes = New-Object byte[] 32
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($ownerBytes)
        $random.GetBytes($appBytes)
    } finally { $random.Dispose() }
    $ownerPassword = [BitConverter]::ToString($ownerBytes).Replace('-', '').ToLowerInvariant()
    $appPassword = [BitConverter]::ToString($appBytes).Replace('-', '').ToLowerInvariant()
    $content = "STACK_DB_PASSWORD=$ownerPassword`nSTACK_APP_PASSWORD=$appPassword`nSTACK_POSTGRES_PORT=55432`nSTACK_REDIS_PORT=6380`nSTACK_MCP_PORT=8001`n"
    [System.IO.File]::WriteAllText((Join-Path $projectRoot '.env.docker'), $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Created .env.docker with random local passwords (not displayed).'
}
docker compose --env-file .env.docker -f compose.full.yaml up -d --build --wait
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Stack is ready. MCP: http://127.0.0.1:8001/mcp (or your configured port).'
