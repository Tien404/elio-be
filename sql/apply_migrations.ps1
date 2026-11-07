<#
.SYNOPSIS
  Creates the ELIO database (if missing) and applies sql/migrations/*.sql in order with sqlcmd.

.EXAMPLE
  # Windows login on the local default instance -> elio_dev
  powershell -ExecutionPolicy Bypass -File sql/apply_migrations.ps1

.EXAMPLE
  # SQL login / other server / other database name
  powershell -ExecutionPolicy Bypass -File sql/apply_migrations.ps1 -Server "tcp:myhost,1433" -Database elio_test -User sa

.NOTES
  Every migration is idempotent (it records itself in dbo.schema_migrations and skips when
  already applied), so re-running this script is safe. Uses a DDL-capable account; the API
  itself must use a separate least-privilege login and never migrates on startup.
#>
param(
    [string]$Server = "localhost",
    [string]$Database = "elio_dev",
    [string]$User,
    [switch]$SkipCreate
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$auth = @("-E")
if ($User) {
    $secure = Read-Host "Password for $User" -AsSecureString
    $env:SQLCMDPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    $auth = @("-U", $User)
}

# -b: stop on error, -I: QUOTED_IDENTIFIER ON (needed for filtered indexes), -C: trust local dev cert
function Invoke-Sql([string]$db, [string]$file, [string[]]$extra = @()) {
    Write-Host "==> $([IO.Path]::GetFileName($file)) on [$db]"
    & sqlcmd -S $Server @auth -C -b -I -d $db -i $file @extra
    if ($LASTEXITCODE -ne 0) { throw "sqlcmd failed on $file (exit $LASTEXITCODE)" }
}

try {
    if (-not $SkipCreate) {
        Invoke-Sql "master" (Join-Path $root "setup/create_database.sql") @("-v", "DbName=$Database")
    }
    Get-ChildItem (Join-Path $root "migrations") -Filter "*.sql" | Sort-Object Name | ForEach-Object {
        Invoke-Sql $Database $_.FullName
    }
    Write-Host "All migrations applied to [$Database]." -ForegroundColor Green
}
finally {
    Remove-Item Env:\SQLCMDPASSWORD -ErrorAction SilentlyContinue
}
