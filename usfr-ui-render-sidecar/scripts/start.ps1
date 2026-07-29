param(
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($EnvFile) {
    $resolvedEnvFile = (Resolve-Path -LiteralPath $EnvFile).Path
    foreach ($line in [System.IO.File]::ReadAllLines($resolvedEnvFile)) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], "Process")
    }
}

$manifest = Get-Content -LiteralPath (Join-Path $projectRoot "sidecar-manifest.json") -Raw | ConvertFrom-Json
$env:USFR_UI_SIDECAR_PROJECT_DIR = $projectRoot
$env:USFR_UI_RENDER_MODEL_ID = [string]$manifest.model_id
$env:USFR_UI_RENDER_MODEL_SHA256 = [string]$manifest.model_sha256
$env:USFR_UI_SIDECAR_HOST = "127.0.0.1"

Push-Location $projectRoot
try {
    & npm.cmd run start --silent
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
