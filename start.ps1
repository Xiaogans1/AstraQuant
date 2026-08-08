$ErrorActionPreference = "Stop"

$worktreeRoot = Join-Path $PSScriptRoot ".worktrees\phase-1-desktop-platform"
$projectRoot = if (Test-Path -LiteralPath (Join-Path $worktreeRoot "scripts\dev.ps1")) {
    $worktreeRoot
}
else {
    $PSScriptRoot
}
$launcher = Join-Path $projectRoot "scripts\dev.ps1"

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "AstraQuant development launcher was not found: $launcher"
}

& $launcher
