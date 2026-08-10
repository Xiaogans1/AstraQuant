param(
    [ValidateSet("Python", "Desktop", "Rust", "All")]
    [string]$Scope = "All"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$runId = [guid]::NewGuid().ToString("n")
$tempRoot = Join-Path $projectRoot ".astraquant/test-tmp/$runId"
$logRoot = Join-Path $projectRoot ".astraquant/test-logs/$runId"
$previousLocation = Get-Location

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    $logPath = Join-Path $logRoot "$Name.log"
    $exitCode = 0
    $transcriptStarted = $false
    try {
        Start-Transcript -Path $logPath -Force | Out-Null
        $transcriptStarted = $true
        & $FilePath @ArgumentList
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($transcriptStarted) {
            Stop-Transcript | Out-Null
        }
    }
    if ($exitCode -ne 0) {
        throw "Verification command '$Name' failed with exit code $exitCode. Log: $logPath"
    }
}

function Assert-CommandAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "Required verification command is missing: $CommandName"
    }
}

try {
    Set-Location -LiteralPath $projectRoot
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

    if ($Scope -in @("Python", "All")) {
        Assert-CommandAvailable -CommandName "uv"
        $pytestTemp = Join-Path $tempRoot "pytest"
        Invoke-Checked -Name "python-pytest" -FilePath "uv" -ArgumentList @("run", "pytest", "-q", "--basetemp", $pytestTemp)
        Invoke-Checked -Name "python-ruff-check" -FilePath "uv" -ArgumentList @("run", "ruff", "check", ".")
        Invoke-Checked -Name "python-ruff-format" -FilePath "uv" -ArgumentList @("run", "ruff", "format", "--check", ".")
        Invoke-Checked -Name "python-mypy" -FilePath "uv" -ArgumentList @("run", "mypy")
        Invoke-Checked -Name "repository-policy" -FilePath "uv" -ArgumentList @("run", "python", "tools/repository_policy.py")
    }

    if ($Scope -in @("Desktop", "All")) {
        Assert-CommandAvailable -CommandName "pnpm"
        Invoke-Checked -Name "desktop-test" -FilePath "pnpm" -ArgumentList @("--dir", "apps/desktop", "test")
        Invoke-Checked -Name "desktop-check" -FilePath "pnpm" -ArgumentList @("--dir", "apps/desktop", "check")
        Invoke-Checked -Name "desktop-build" -FilePath "pnpm" -ArgumentList @("--dir", "apps/desktop", "build")
    }

    if ($Scope -in @("Rust", "All")) {
        Assert-CommandAvailable -CommandName "cargo"
        $cargoManifest = "apps/desktop/src-tauri/Cargo.toml"
        Invoke-Checked -Name "rust-format" -FilePath "cargo" -ArgumentList @("fmt", "--manifest-path", $cargoManifest, "--all", "--", "--check")
        Invoke-Checked -Name "rust-clippy" -FilePath "cargo" -ArgumentList @("clippy", "--manifest-path", $cargoManifest, "--all-targets", "--", "-D", "warnings")
        Invoke-Checked -Name "rust-test" -FilePath "cargo" -ArgumentList @("test", "--manifest-path", $cargoManifest)
    }

    Write-Output "Verification passed for scope '$Scope'. Logs: $logRoot"
}
finally {
    Set-Location -LiteralPath $previousLocation
}
