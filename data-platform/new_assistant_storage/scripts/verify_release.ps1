$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$archivePath = Join-Path $projectRoot 'dist\assistant-storage-mcp.zip'
if (-not (Test-Path -LiteralPath $archivePath)) { throw 'Build the source archive first: python -m scripts.package_release' }
$stamp = [Guid]::NewGuid().ToString('N').Substring(0, 10)
$projectName = "assistant-check-$stamp"
$cleanRoot = Join-Path $projectRoot "dist\clean-check-$stamp"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($archivePath, $cleanRoot)
if ((Test-Path -LiteralPath (Join-Path $cleanRoot '.env')) -or (Test-Path -LiteralPath (Join-Path $cleanRoot '.env.docker'))) {
    throw 'The archive unexpectedly contains local configuration.'
}
$previousLocation = Get-Location
$names = @('COMPOSE_PROJECT_NAME', 'STACK_POSTGRES_PORT', 'STACK_REDIS_PORT', 'STACK_MCP_PORT')
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    Set-Location -LiteralPath $cleanRoot
    $env:COMPOSE_PROJECT_NAME = $projectName
    $env:STACK_POSTGRES_PORT = '55433'
    $env:STACK_REDIS_PORT = '6381'
    $env:STACK_MCP_PORT = '18001'
    & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
    if ($LASTEXITCODE -ne 0) { throw 'Fresh start failed.' }
    docker compose --env-file .env.docker -f compose.full.yaml --profile tools run --rm tests
    if ($LASTEXITCODE -ne 0) { throw 'Fresh stack integration tests failed.' }
    docker compose --env-file .env.docker -f compose.full.yaml exec -T mcp python -m scripts.verify_persistence write --token $stamp
    if ($LASTEXITCODE -ne 0) { throw 'Control write failed.' }
    docker compose --env-file .env.docker -f compose.full.yaml restart postgres mcp
    if ($LASTEXITCODE -ne 0) { throw 'Restart failed.' }
    docker compose --env-file .env.docker -f compose.full.yaml up -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'Readiness check after restart failed.' }
    docker compose --env-file .env.docker -f compose.full.yaml exec -T mcp python -m scripts.verify_persistence read --token $stamp
    if ($LASTEXITCODE -ne 0) { throw 'The control event did not persist.' }
    $report = @{
        project = $projectName
        clean_archive = $true
        fresh_configuration = $true
        integration_tests = 'passed (see test output)'
        postgres_restart_persistence = 'passed'
        finished_at = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json
    [System.IO.File]::WriteAllText((Join-Path $projectRoot 'docs\reports\fresh_install.json'), $report, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Fresh archive install, tests and database restart persistence passed.'
} finally {
    if (Test-Path -LiteralPath (Join-Path $cleanRoot '.env.docker')) {
        Set-Location -LiteralPath $cleanRoot
        docker compose --env-file .env.docker -f compose.full.yaml stop
    }
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    Set-Location -LiteralPath $previousLocation
}
