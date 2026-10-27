$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
function New-LocalPassword {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
}
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
# Upgrade existing installations without rotating their database passwords.
$envPath = Join-Path $projectRoot '.env.docker'
if (-not ([System.IO.File]::ReadAllText($envPath) -match '(?m)^STACK_API_PASSWORD=')) {
    $apiPassword = New-LocalPassword
    [System.IO.File]::AppendAllText($envPath, "`nSTACK_API_PASSWORD=$apiPassword`n", (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Added a separate API database password (not displayed).'
}
docker compose --env-file .env.docker -f compose.full.yaml up -d --build --wait
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Stack is ready. MCP: http://127.0.0.1:8001/mcp (or your configured port).'
