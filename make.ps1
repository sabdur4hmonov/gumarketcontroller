#!/usr/bin/env pwsh
# Windows shim for the Makefile -- `make` is not installed on this box.
# Keep the target list in sync with Makefile; tests/test_make_targets.py enforces it.
param([Parameter(Position = 0)][string]$Target = "help")

$ErrorActionPreference = "Stop"
$PY = ".venv\Scripts\python.exe"

# Runs a native command and fails the build with exit code 1 on any non-zero
# result. Normalising to 1 matters: PowerShell surfaces some child exits as -1,
# which CI reads as a crash rather than a failed check.
function Invoke-Step {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Command $($Arguments -join ' ')" -ForegroundColor Red
        exit 1
    }
}

$Steps = @{
    "venv"      = { Invoke-Step "py" @("-3.11", "-m", "venv", ".venv") }
    "install"   = {
        Invoke-Step "py" @("-3.11", "-m", "venv", ".venv")
        Invoke-Step $PY @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-Step $PY @("-m", "pip", "install", "-e", ".[dev]")
    }
    "up"        = { Invoke-Step "docker" @("compose", "up", "-d", "--wait") }
    "down"      = { Invoke-Step "docker" @("compose", "down") }
    "logs"      = { Invoke-Step "docker" @("compose", "logs", "-f", "--tail=100") }
    "ps"        = { Invoke-Step "docker" @("compose", "ps") }
    "fmt"       = {
        Invoke-Step $PY @("-m", "ruff", "format", "src", "tests", "migrations")
        Invoke-Step $PY @("-m", "ruff", "check", "--fix", "src", "tests", "migrations")
    }
    "lint"      = {
        Invoke-Step $PY @("-m", "ruff", "check", "src", "tests", "migrations")
        Invoke-Step $PY @("-m", "ruff", "format", "--check", "src", "tests", "migrations")
    }
    "typecheck" = { Invoke-Step $PY @("-m", "mypy") }
    "shadow"    = { Invoke-Step $PY @("-m", "gulbot.bot.shadow_sweep") }
    "test"      = { Invoke-Step $PY @("-m", "pytest") }
    "clean"     = { Invoke-Step "docker" @("compose", "down", "-v") }
}

# The gate. Runs in order and stops at the first failure.
$CheckSteps = @("lint", "typecheck", "shadow", "test")

switch ($Target) {
    "help"  { Write-Host "venv install up down logs ps fmt lint typecheck shadow test check clean" }
    "check" { foreach ($step in $CheckSteps) { & $Steps[$step] } }
    default {
        if (-not $Steps.ContainsKey($Target)) { Write-Error "unknown target: $Target"; exit 1 }
        & $Steps[$Target]
    }
}
