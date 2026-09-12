param(
    [Parameter(Mandatory = $true)]
    [string[]]$Models,

    [string]$Repository = "https://github.com/floydtrey/local-model-bench.git",

    [string]$FixtureBranch = "construction-lab-fixtures-v1",

    [string]$ExpectedFixtureCommit = "429ef04722093bf9f355a48b4d236a119f3b03e6",

    [string]$OutputRoot = "local-state/construction-lab/workspaces",

    [switch]$Reset
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function ConvertTo-SafeName {
    param([Parameter(Mandatory = $true)][string]$Value)
    return ($Value -replace '[^A-Za-z0-9._-]', '_')
}

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $Here)
$ResolvedOutputRoot = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    [System.IO.Path]::GetFullPath($OutputRoot)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputRoot))
}

New-Item -ItemType Directory -Path $ResolvedOutputRoot -Force | Out-Null

$Prepared = @()
foreach ($Model in $Models) {
    $SafeModel = ConvertTo-SafeName $Model
    $Destination = Join-Path $ResolvedOutputRoot $SafeModel

    if (Test-Path -LiteralPath $Destination) {
        if (-not $Reset) {
            throw "Workspace already exists for $Model at $Destination. Use -Reset to rebuild disposable clones."
        }
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }

    Write-Host "Cloning fixtures for $Model -> $Destination" -ForegroundColor Cyan
    & git clone --quiet --branch $FixtureBranch --single-branch $Repository $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "git clone failed for $Model with exit code $LASTEXITCODE"
    }

    $Actual = (& git -C $Destination rev-parse HEAD).Trim()
    if ($Actual -ne $ExpectedFixtureCommit) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
        throw "Fixture commit mismatch for $Model. Expected $ExpectedFixtureCommit but cloned $Actual. Workspace removed."
    }

    # Models never receive Git as a tool. The clone metadata is retained only for
    # deterministic provenance and operator-side post-run diff inspection.
    $Prepared += [pscustomobject]@{
        model = $Model
        safe_model = $SafeModel
        workspace = $Destination
        fixture_branch = $FixtureBranch
        fixture_commit = $Actual
    }
}

$Prepared | Format-Table -AutoSize
Write-Host ""
Write-Host "Prepared $($Prepared.Count) isolated Construction Lab workspace(s)." -ForegroundColor Green
