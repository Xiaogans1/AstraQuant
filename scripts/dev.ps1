param(
    [switch]$SkipSync
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$previousLocation = Get-Location

try {
    Set-Location -LiteralPath $projectRoot

    foreach ($commandName in @("uv", "pnpm", "cargo")) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "Required development command is missing: $commandName"
        }
    }

    if (-not $SkipSync) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".venv"))) {
            uv sync --locked --all-packages
            if ($LASTEXITCODE -ne 0) {
                throw "uv dependency synchronization failed"
            }
        }

        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "node_modules"))) {
            pnpm install --frozen-lockfile
            if ($LASTEXITCODE -ne 0) {
                throw "pnpm dependency installation failed"
            }
        }
    }

    pnpm dev
    if ($LASTEXITCODE -ne 0) {
        throw "AstraQuant development runtime exited with code $LASTEXITCODE"
    }
}
finally {
    Set-Location -LiteralPath $previousLocation
}
