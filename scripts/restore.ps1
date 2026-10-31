param([Parameter(Mandatory=$true)][string]$Path,
      [Parameter(Mandatory=$true)][string]$TargetDatabase)
$ErrorActionPreference = 'Stop'
# Only a newly created database: never --clean against a working database.
& createdb $TargetDatabase
if ($LASTEXITCODE -ne 0) { throw 'Target must be a new database' }
& pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname $TargetDatabase $Path
if ($LASTEXITCODE -ne 0) { throw 'Restore failed' }
& psql --dbname $TargetDatabase --set ON_ERROR_STOP=1 --command 'SELECT count(*) AS restored_events FROM public.events; SELECT version FROM public.schema_migrations ORDER BY version;'
if ($LASTEXITCODE -ne 0) { throw 'Restore verification failed' }
