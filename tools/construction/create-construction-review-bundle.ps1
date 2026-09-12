param(
    [string[]]$Models = @(
        "qwen3.5_9b",
        "gemma4_12b",
        "gpt-oss_20b",
        "qwen3.6_27b",
        "qwen3-coder_30b",
        "qwen3.6_35b"
    ),

    [string[]]$Tasks = @(
        "repair-calculator-average",
        "add-json-report",
        "remove-legacy-mode"
    ),

    [string]$WorkspaceRoot = "local-state/construction-lab/workspaces",

    [string]$RunRoot = "local-state/construction-lab/runs",

    [string]$OutputRoot = "local-state/construction-lab/review-bundle",

    [string]$ZipPath = "construction-lab-review-bundle.zip",

    [string]$RoundLabel
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $Here)

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function ConvertTo-ReviewName {
    param([Parameter(Mandatory = $true)][string]$Path)
    return ($Path -replace '[\\/:*?"<>|]', '_')
}

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

function Get-PathSegment {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$ParameterName
    )
    if ($Value -notmatch '\A[A-Za-z0-9][A-Za-z0-9._-]*\z') {
        throw "$ParameterName must start with an ASCII letter or digit and contain only letters, digits, periods, underscores, or hyphens: $Value"
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

$ResolvedWorkspaceRoot = Resolve-RepoPath $WorkspaceRoot
$ResolvedRunRoot = Resolve-RepoPath $RunRoot
$ResolvedOutputRoot = Resolve-RepoPath $OutputRoot
$ResolvedZipPath = Resolve-RepoPath $ZipPath

if (-not [string]::IsNullOrWhiteSpace($RoundLabel)) {
    $SafeRound = Get-RoundName $RoundLabel
    $ResolvedWorkspaceRoot = Resolve-ContainedChild $ResolvedWorkspaceRoot $SafeRound
    $ResolvedRunRoot = Resolve-ContainedChild $ResolvedRunRoot $SafeRound
    $ResolvedOutputRoot = Resolve-ContainedChild $ResolvedOutputRoot $SafeRound
    if ($ZipPath -eq "construction-lab-review-bundle.zip") {
        $ResolvedZipPath = Resolve-RepoPath ("construction-lab-review-bundle-" + $SafeRound + ".zip")
    }
}

if (Test-Path -LiteralPath $ResolvedZipPath) {
    throw "Refusing to overwrite an existing review bundle: $ResolvedZipPath"
}

if (Test-Path -LiteralPath $ResolvedOutputRoot) {
    Remove-Item -LiteralPath $ResolvedOutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $ResolvedOutputRoot -Force | Out-Null

foreach ($Model in $Models) {
    $ModelSegment = Get-PathSegment $Model "Model"
    $Workspace = Resolve-ContainedChild $ResolvedWorkspaceRoot $ModelSegment
    if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
        Write-Warning "Skipping missing workspace: $Workspace"
        continue
    }

    $ModelOut = Resolve-ContainedChild $ResolvedOutputRoot $ModelSegment
    $FilesOut = Join-Path $ModelOut "files"
    New-Item -ItemType Directory -Path $FilesOut -Force | Out-Null

    git -C $Workspace status --short --untracked-files=all |
        Set-Content -LiteralPath (Join-Path $ModelOut "git-status.txt") -Encoding utf8

    git -C $Workspace diff --binary HEAD -- |
        Set-Content -LiteralPath (Join-Path $ModelOut "tracked-workspace.diff") -Encoding utf8

    $TrackedChanged = @(
        git -C $Workspace diff --name-only HEAD --
    )
    $Untracked = @(
        git -C $Workspace ls-files --others --exclude-standard
    ) | Where-Object { $_ -ne ".construction-lab-workspace.json" }
    $ChangedFiles = @($TrackedChanged + $Untracked) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique

    $ChangedFiles |
        Set-Content -LiteralPath (Join-Path $ModelOut "changed-files.txt") -Encoding utf8

    foreach ($RelativePath in $ChangedFiles) {
        $SafeName = ConvertTo-ReviewName $RelativePath
        $CurrentPath = Join-Path $Workspace $RelativePath
        $CurrentOut = Join-Path $FilesOut "$SafeName.current.txt"
        $OriginalOut = Join-Path $FilesOut "$SafeName.original.txt"

        if (Test-Path -LiteralPath $CurrentPath -PathType Leaf) {
            Copy-Item -LiteralPath $CurrentPath -Destination $CurrentOut
        }
        else {
            "FILE DELETED" | Set-Content -LiteralPath $CurrentOut -Encoding utf8
        }

        # Untracked files are intentionally part of the review bundle, but by
        # definition they have no HEAD version. Do not invoke `git show` for them:
        # PowerShell can promote git's expected stderr into a terminating error
        # under ErrorActionPreference=Stop before LASTEXITCODE can be inspected.
        if ($Untracked -contains $RelativePath) {
            "FILE DID NOT EXIST IN BASELINE" |
                Set-Content -LiteralPath $OriginalOut -Encoding utf8
        }
        else {
            # Every remaining changed path came from `git diff HEAD`, so it was
            # tracked in the fixture baseline even when it is now deleted.
            $Baseline = & git -C $Workspace show "HEAD:$RelativePath"
            if ($LASTEXITCODE -ne 0) {
                throw "Unable to read baseline content for tracked path: $RelativePath"
            }
            $Baseline | Set-Content -LiteralPath $OriginalOut -Encoding utf8
        }
    }

    foreach ($Task in $Tasks) {
        $TaskSegment = Get-PathSegment $Task "Task"
        $TaskRoot = Resolve-ContainedChild (Resolve-ContainedChild $ResolvedRunRoot $ModelSegment) $TaskSegment
        if (-not (Test-Path -LiteralPath $TaskRoot -PathType Container)) {
            continue
        }

        $Latest = Get-ChildItem -LiteralPath $TaskRoot -Directory |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($null -eq $Latest) {
            continue
        }

        $TaskOut = Resolve-ContainedChild $ModelOut $TaskSegment
        New-Item -ItemType Directory -Path $TaskOut -Force | Out-Null

        foreach ($EvidenceName in @(
            "result.json",
            "events.json",
            "initial-snapshot.json",
            "final-snapshot.json",
            "baseline-verification.json",
            "assessor-verification.json",
            "telemetry.csv"
        )) {
            $Source = Join-Path $Latest.FullName $EvidenceName
            if (Test-Path -LiteralPath $Source -PathType Leaf) {
                Copy-Item -LiteralPath $Source -Destination $TaskOut
            }
        }
    }
}

Compress-Archive `
    -Path (Join-Path $ResolvedOutputRoot "*") `
    -DestinationPath $ResolvedZipPath `
    -CompressionLevel Optimal

Write-Host ""
Write-Host "Construction Lab review bundle created:" -ForegroundColor Green
Write-Host $ResolvedZipPath
