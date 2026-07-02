[CmdletBinding()]
param(
    [string]$PythonLauncher = "py",
    [string]$PythonVersion = "-3.13"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

& $PythonLauncher $PythonVersion -m venv .venv
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual-environment Python was not created."
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -e .
& $Python -m pip install pytest MetaTrader5

Write-Output "Windows environment setup complete. Copy .env.example to .env and populate secrets locally."
