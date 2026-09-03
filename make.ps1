#!/usr/bin/env pwsh
# Windows shim for the Makefile -- `make` is not installed on this box.
# Keep the target list in sync with Makefile.
param([Parameter(Position = 0)][string]$Target = "help")

$ErrorActionPreference = "Stop"
$PY = ".venv\Scripts\python.exe"

function Invoke-Step($cmd, $arguments) {
    & $cmd @arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Target) {
    "help"      { Write-Host "venv install up down logs ps fmt lint typecheck test check clean" }
    "venv"      { Invoke-Step "py" @("-3.11", "-m", "venv", ".venv") }
    "install"   {
        Invoke-Step "py" @("-3.11", "-m", "venv", ".venv")
        Invoke-Step $PY @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-Step $PY @("-m", "pip", "install", "-e", ".[dev]")
    }
    "up"        { Invoke-Step "docker" @("compose", "up", "-d", "--wait") }
    "down"      { Invoke-Step "docker" @("compose", "down") }
    "logs"      { Invoke-Step "docker" @("compose", "logs", "-f", "--tail=100") }
    "ps"        { Invoke-Step "docker" @("compose", "ps") }
    "fmt"       {
        Invoke-Step $PY @("-m", "ruff", "format", "src", "tests")
        Invoke-Step $PY @("-m", "ruff", "check", "--fix", "src", "tests")
    }
    "lint"      {
        Invoke-Step $PY @("-m", "ruff", "check", "src", "tests")
        Invoke-Step $PY @("-m", "ruff", "format", "--check", "src", "tests")
    }
    "typecheck" { Invoke-Step $PY @("-m", "mypy") }
    "test"      { Invoke-Step $PY @("-m", "pytest") }
    "check"     {
        # CP2 adds the handler-shadowing sweep here.
        foreach ($t in @("lint", "typecheck", "test")) { & $PSCommandPath $t }
    }
    "clean"     { Invoke-Step "docker" @("compose", "down", "-v") }
    default     { Write-Error "unknown target: $Target"; exit 1 }
}
