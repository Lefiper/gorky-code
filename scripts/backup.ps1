param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
# pg_dump reads PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE from the environment.
& pg_dump --format=custom --no-owner --no-acl --file $Path
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }
& pg_restore --list $Path | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Archive validation failed' }
