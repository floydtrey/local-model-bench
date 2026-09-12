param(
    [Parameter(Mandatory = $true)]
    [string[]]$Models,

    [string]$Repository = "https://github.com/floydtrey/local-model-bench.git",

    [string]$FixtureBranch = "construction-lab-fixtures-v1",

    [string]$ExpectedFixtureCommit = "429ef04722093bf9f355a48b4d236a119f3b03e6",

    [string]$OutputRoot = "local-state/construction-lab/workspaces",

    [string]$RoundLabel = "default",

    [switch]$Reset
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function ConvertTo-SafeName {
    param([Parameter(Mandatory = $true)][string]$Value)
    return ($Value -replace '[^A-Za-z0-9._-]', '_')
}

function Get-RoundName {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value -notmatch '\A[A-Za-z0-9][A-Za-z0-9._-]*\z') {
        throw "RoundLabel must start with an ASCII letter or digit and contain only letters, digits, periods, underscores, or hyphens."
    }
    return $Value
}

function Resolve-ContainedChild {
    param(
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Child
    )
    $ResolvedParent = [System.IO.Path]::GetFullPath($Parent)
    $Prefix = $ResolvedParent.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar
    $Candidate = [System.IO.Path]::GetFullPath((Join-Path $ResolvedParent $Child))
    if (-not $Candidate.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved child path escapes its configured root: $Candidate"
    }
    return $Candidate
}

function Remove-DisposableWorkspace {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedModelName,
        [Parameter(Mandatory = $true)][string]$ExpectedModel,
        [Parameter(Mandatory = $true)][string]$ExpectedRound,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit
    )

    $Marker = Join-Path $Path ".construction-lab-workspace.json"
    if (-not (Test-Path -LiteralPath $Marker -PathType Leaf)) {
        throw "Refusing to reset $Path because it is not a marked disposable Construction Lab workspace."
    }
    $Metadata = Get-Content -LiteralPath $Marker -Raw | ConvertFrom-Json
    if (
        $Metadata.model -ne $ExpectedModelName -or
        $Metadata.safe_model -ne $ExpectedModel -or
        $Metadata.round_label -ne $ExpectedRound -or
        $Metadata.fixture_commit -ne $ExpectedCommit -or
        [System.IO.Path]::GetFullPath([string]$Metadata.workspace) -ne [System.IO.Path]::GetFullPath($Path)
    ) {
        throw "Refusing to reset $Path because its disposable-workspace marker does not match this model, round, fixture commit, and path."
    }
    Remove-Item -LiteralPath $Path -Recurse -Force
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
$SafeRound = Get-RoundName $RoundLabel
$RoundRoot = Resolve-ContainedChild $ResolvedOutputRoot $SafeRound
New-Item -ItemType Directory -Path $RoundRoot -Force | Out-Null

$Prepared = @()
foreach ($Model in $Models) {
    $SafeModel = ConvertTo-SafeName $Model
    if ([string]::IsNullOrWhiteSpace($SafeModel) -or $SafeModel -in @(".", "..")) {
        throw "Model name does not produce a safe workspace directory name: $Model"
    }
    $Destination = Resolve-ContainedChild $RoundRoot $SafeModel

    if (Test-Path -LiteralPath $Destination) {
        if (-not $Reset) {
            throw "Workspace already exists for $Model at $Destination. Use -Reset to rebuild disposable clones."
        }
        Remove-DisposableWorkspace `
            -Path $Destination `
            -ExpectedModelName $Model `
            -ExpectedModel $SafeModel `
            -ExpectedRound $RoundLabel `
            -ExpectedCommit $ExpectedFixtureCommit
    }

    Write-Host "Cloning fixtures for $Model -> $Destination" -ForegroundColor Cyan
    & git clone --quiet --branch $FixtureBranch --single-branch $Repository $Destination
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path -LiteralPath $Destination) {
            Remove-Item -LiteralPath $Destination -Recurse -Force
        }
        throw "git clone failed for $Model with exit code $LASTEXITCODE"
    }

    $Actual = (& git -C $Destination rev-parse HEAD).Trim()
    if ($Actual -ne $ExpectedFixtureCommit) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
        throw "Fixture commit mismatch for $Model. Expected $ExpectedFixtureCommit but cloned $Actual. Workspace removed."
    }

    # Models never receive Git as a tool. The clone metadata is retained only for
    # deterministic provenance and operator-side post-run diff inspection.
    $WorkspaceMetadata = [ordered]@{
        model = $Model
        safe_model = $SafeModel
        workspace = $Destination
        round_label = $RoundLabel
        fixture_branch = $FixtureBranch
        fixture_commit = $Actual
    }
    $WorkspaceMetadata | ConvertTo-Json | Set-Content `
        -LiteralPath (Join-Path $Destination ".construction-lab-workspace.json") `
        -Encoding utf8
    $Prepared += [pscustomobject]$WorkspaceMetadata
}

$Prepared | Format-Table -AutoSize
Write-Host ""
Write-Host "Prepared $($Prepared.Count) isolated Construction Lab workspace(s) for round '$RoundLabel'." -ForegroundColor Green
