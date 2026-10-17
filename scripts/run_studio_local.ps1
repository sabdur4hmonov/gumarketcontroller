<#
.SYNOPSIS
  Taklifnoma Studio on THIS PC (CP27): the shop bot and the page server from this
  worktree, against its own database gulbot_cp27, pages on http://127.0.0.1:8088.

.DESCRIPTION
  Secrets are read from the main checkout's .env into THIS PowerShell process (and
  the processes it starts) only: nothing is written to disk, nothing is printed.
  The page server opens in its own window; the bot runs in this one. Ctrl+C stops
  each. It refuses to start while another gulbot bot process is running, because
  one bot token must never be polled from two places (Telegram answers 409).

  -DryRun shows what WOULD run (variable NAMES only) and starts nothing.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run_studio_local.ps1
#>
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot "..\..\gulbot\.env"),
    [ValidateSet("both", "bot", "web")][string]$Run = "both",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = (Resolve-Path (Join-Path $PSScriptRoot "..\..\gulbot\.venv\Scripts\python.exe")).Path

if (-not (Test-Path $EnvFile)) { throw "No .env at $EnvFile (pass -EnvFile)." }
$loaded = @()
foreach ($line in Get-Content -Path $EnvFile -Encoding UTF8) {
    $text = $line.Trim()
    if ($text -eq "" -or $text.StartsWith("#") -or -not $text.Contains("=")) { continue }
    $at = $text.IndexOf("=")
    $name = $text.Substring(0, $at).Trim().ToUpper()
    $value = $text.Substring($at + 1).Trim().Trim('"').Trim("'")
    Set-Item -Path "env:$name" -Value $value
    $loaded += $name
}
if (($env:ENVIRONMENT + "").Trim().ToLower() -eq "production") {
    throw "ENVIRONMENT=production in ${EnvFile}: this script is for a local test only."
}

# This test's own corner: its database and Redis indexes, never CP25's.
$overrides = [ordered]@{
    POSTGRES_DB        = "gulbot_cp27"
    POSTGRES_TEST_DB   = "gulbot_cp27_test"
    REDIS_DB_FSM       = "3"
    REDIS_DB_BROKER    = "4"
    REDIS_DB_RESULTS   = "5"
    PLATFORM_BOT_TOKEN = ""
    WEB_HOST           = "127.0.0.1"
    WEB_PORT           = "8088"
    PUBLIC_BASE_URL    = "http://127.0.0.1:8088"
    PYTHONPATH         = (Join-Path $root "src")
    PYTHONUNBUFFERED   = "1"
}
foreach ($key in $overrides.Keys) { Set-Item -Path "env:$key" -Value $overrides[$key] }

$running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like "python*" -and $_.CommandLine -match "gulbot\.bot\.run"
})
if ($DryRun) {
    "Would load from .env (names only): " + ($loaded -join ", ")
    "Would override: " + ($overrides.Keys -join ", ")
    "Python: $python"
    "Worktree: $root"
    "Other gulbot bot processes now: $($running.Count)"
    "Would run: migrate (alembic upgrade head), then $Run"
    return
}
if ($running.Count -gt 0 -and $Run -ne "web") {
    throw "Another gulbot bot is running (PID $($running[0].ProcessId)). Stop it first: one token, one poller."
}

Push-Location $root
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }
    if ($Run -in @("both", "web")) {
        Start-Process -FilePath $python -ArgumentList "-m", "gulbot.web.run" -WorkingDirectory $root
        "Page server: http://127.0.0.1:8088 (its own window)"
    }
    if ($Run -in @("both", "bot")) {
        "Bot: starting here. Ctrl+C stops it."
        & $python -m gulbot.bot.run
    }
}
finally {
    Pop-Location
}
