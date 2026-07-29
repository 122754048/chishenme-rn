param(
    [string]$EnvFile = "C:\Users\zhaocx04\Documents\New project\usfr-local-console\.env",
    [string]$SkillRoot = "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication"
)

$ErrorActionPreference = "Stop"

foreach ($line in [System.IO.File]::ReadAllLines((Resolve-Path -LiteralPath $EnvFile).Path)) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
        continue
    }
    $parts = $trimmed.Split("=", 2)
    [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], "Process")
}

$projectRoot = $env:USFR_UI_SIDECAR_PROJECT_DIR
if (-not $projectRoot -or -not (Test-Path -LiteralPath $projectRoot -PathType Container)) {
    throw "USFR_UI_SIDECAR_PROJECT_DIR is unavailable"
}
if (-not (Test-Path -LiteralPath $SkillRoot -PathType Container)) {
    throw "USFR Skill root is unavailable"
}

$sidecarPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $sidecarPython -PathType Leaf)) {
    throw "Sidecar Python environment is unavailable; run scripts/install.ps1"
}
$driverPython = (Get-Command python -ErrorAction Stop).Source

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:USFR_UI_SIDECAR_IDLE_TIMEOUT_SECONDS = "5"
& $driverPython (Join-Path $projectRoot "scripts\smoke_driver.py") --project-root $projectRoot --skill-root $SkillRoot
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
