param(
    [switch]$SkipSync
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$previousLocation = Get-Location

try {
    Set-Location -LiteralPath $projectRoot

    foreach ($commandName in @("uv", "node", "npm", "cargo")) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "Required development command is missing: $commandName"
        }
    }

    $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
    if ($pnpmCommand) {
        $pnpmExecutable = $pnpmCommand.Source
        $pnpmPrefix = @()
    }
    else {
        $corepackCommand = Get-Command corepack -ErrorAction SilentlyContinue
        if (-not $corepackCommand) {
            throw "Node.js Corepack is missing; reinstall Node.js 24 or newer"
        }
        $env:COREPACK_ENABLE_DOWNLOAD_PROMPT = "0"
        $pnpmExecutable = $corepackCommand.Source
        $pnpmPrefix = @("pnpm")
    }

    function Invoke-Pnpm {
        param(
            [Parameter(ValueFromRemainingArguments = $true)]
            [string[]]$PnpmArguments
        )

        & $pnpmExecutable @pnpmPrefix @PnpmArguments
        if ($LASTEXITCODE -ne 0) {
            throw "pnpm command failed with code $LASTEXITCODE"
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
            Invoke-Pnpm install --frozen-lockfile
        }
    }

    npm --prefix apps/desktop run tauri -- dev
    if ($LASTEXITCODE -ne 0) {
        throw "AstraQuant development runtime exited with code $LASTEXITCODE"
    }
}
finally {
    Set-Location -LiteralPath $previousLocation
}
