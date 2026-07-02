[CmdletBinding()]
param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$candidates = [System.Collections.Generic.List[string]]::new()
if ($PythonPath) {
    $candidates.Add($PythonPath)
}
else {
    foreach ($name in @("python.exe", "python3.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {
            $candidates.Add($command.Source)
        }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($line in (& py -0p 2>$null)) {
            if ($line -match "([A-Za-z]:\\.+\\python\.exe)\s*$") {
                $candidates.Add($matches[1])
            }
        }
    }
}

$BasePython = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        continue
    }
    try {
        $rawVersion = & $candidate -c "import platform; print(platform.python_version())" 2>$null
    }
    catch {
        continue
    }
    if ($LASTEXITCODE -ne 0) {
        continue
    }
    $VersionInfo = [version]($rawVersion | Select-Object -Last 1)
    if (
        $VersionInfo.Major -eq 3 -and
        $VersionInfo.Minor -ge 10 -and
        $VersionInfo.Minor -le 13
    ) {
        $BasePython = $candidate
        break
    }
}
if (-not $BasePython) {
    throw "Python 3.10 through 3.13 was not found. Pass -PythonPath with a compatible python.exe."
}

& $BasePython -m venv .venv
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual-environment Python was not created."
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -e .
& $Python -m pip install pytest MetaTrader5

Write-Output "Windows environment setup complete. Copy .env.example to .env and populate secrets locally."
