$ErrorActionPreference = "Stop"

function Test-DevelopmentRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    return Test-Path -LiteralPath (Join-Path $Path "scripts\dev.ps1") -PathType Leaf
}

$candidates = [System.Collections.Generic.List[string]]::new()
if (-not [string]::IsNullOrWhiteSpace($env:ASTRAQUANT_WORKTREE)) {
    $candidates.Add($env:ASTRAQUANT_WORKTREE)
}

Push-Location $PSScriptRoot
try {
    $worktreeLines = & git worktree list --porcelain 2>$null
}
finally {
    Pop-Location
}

$registeredWorktrees = @(
    $worktreeLines |
        Where-Object { $_ -like "worktree *" } |
        ForEach-Object { $_.Substring("worktree ".Length) }
)
[array]::Reverse($registeredWorktrees)
foreach ($worktree in $registeredWorktrees) {
    if ($worktree -ne $PSScriptRoot) {
        $candidates.Add($worktree)
    }
}
$candidates.Add($PSScriptRoot)

$projectRoot = $candidates |
    Where-Object { Test-DevelopmentRoot -Path $_ } |
    ForEach-Object { (Resolve-Path -LiteralPath $_).Path } |
    Select-Object -First 1

if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    throw "AstraQuant development worktree was not found"
}

$launcher = Join-Path $projectRoot "scripts\dev.ps1"

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "AstraQuant development launcher was not found: $launcher"
}

& $launcher
