# Local dev launcher: starts the portable PostgreSQL in .pgsql/.pgdata, then Django runserver.
# Usage:  powershell -ExecutionPolicy Bypass -File .\run-dev.ps1
$root = $PSScriptRoot
$env:DJANGO_DEBUG = "1"
$env:WS_OTP_DEBUG_ECHO = "1"
$env:DJANGO_SSL_REDIRECT = "0"
$env:PYTHONIOENCODING = "utf-8"

& "$root\.pgsql\bin\pg_ctl.exe" -D "$root\.pgdata" status *> $null
if ($LASTEXITCODE -ne 0) {
    & "$root\.pgsql\bin\pg_ctl.exe" -D "$root\.pgdata" -l "$root\.pgdata\server.log" -o "-p 5432 -c listen_addresses=localhost" start
}
& "$root\.venv\Scripts\python.exe" "$root\manage.py" runserver 127.0.0.1:8000
# Stop the database afterwards with:  .\.pgsql\bin\pg_ctl.exe -D .pgdata stop
