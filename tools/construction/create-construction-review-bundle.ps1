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

    [string]$ZipPath = "construction-lab-review-bundle.zip"
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

$ResolvedWorkspaceRoot = Resolve-RepoPath $WorkspaceRoot
$ResolvedRunRoot = Resolve-RepoPath $RunRoot
$ResolvedOutputRoot = Resolve-RepoPath $OutputRoot
$ResolvedZipPath = Resolve-RepoPath $ZipPath

if (Test-Path -LiteralPath $ResolvedOutputRoot) {
    Remove-Item -LiteralPath $ResolvedOutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $ResolvedOutputRoot -Force | Out-Null

foreach ($Model in $Models) {
    $Workspace = Join-Path $ResolvedWorkspaceRoot $Model
    if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
        Write-Warning "Skipping missing workspace: $Workspace"
        continue
    }

    $ModelOut = Join-Path $ResolvedOutputRoot $Model
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
    )
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

        $Baseline = & git -C $Workspace show "HEAD:$RelativePath" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Baseline | Set-Content -LiteralPath $OriginalOut -Encoding utf8
        }
        else {
            "FILE DID NOT EXIST IN BASELINE" |
                Set-Content -LiteralPath $OriginalOut -Encoding utf8
        }
    }

    foreach ($Task in $Tasks) {
        $TaskRoot = Join-Path (Join-Path $ResolvedRunRoot $Model) $Task
        if (-not (Test-Path -LiteralPath $TaskRoot -PathType Container)) {
            continue
        }

        $Latest = Get-ChildItem -LiteralPath $TaskRoot -Directory |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($null -eq $Latest) {
            continue
        }

        $TaskOut = Join-Path $ModelOut $Task
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

if (Test-Path -LiteralPath $ResolvedZipPath) {
    Remove-Item -LiteralPath $ResolvedZipPath -Force
}
Compress-Archive `
    -Path (Join-Path $ResolvedOutputRoot "*") `
    -DestinationPath $ResolvedZipPath `
    -CompressionLevel Optimal

Write-Host ""
Write-Host "Construction Lab review bundle created:" -ForegroundColor Green
Write-Host $ResolvedZipPath
