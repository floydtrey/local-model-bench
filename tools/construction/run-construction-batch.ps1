param(
    [Parameter(Mandatory = $true)]
    [string[]]$Models,

    [string[]]$Tasks = @(
        "repair-calculator-average",
        "add-json-report",
        "remove-legacy-mode"
    ),

    [string]$WorkspaceRoot = "local-state/construction-lab/workspaces",

    [string]$ResultRoot = "local-state/construction-lab/runs",

    [string]$CommandBackend = "docker",

    [string]$DockerImage = "python:3.12-slim"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function ConvertTo-SafeName {
    param([Parameter(Mandatory = $true)][string]$Value)
    return ($Value -replace '[^A-Za-z0-9._-]', '_')
}

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $Here)
$Runner = Join-Path $Here "run-construction-task.py"

$ResolvedWorkspaceRoot = if ([System.IO.Path]::IsPathRooted($WorkspaceRoot)) {
    [System.IO.Path]::GetFullPath($WorkspaceRoot)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $WorkspaceRoot))
}

$ResolvedResultRoot = if ([System.IO.Path]::IsPathRooted($ResultRoot)) {
    [System.IO.Path]::GetFullPath($ResultRoot)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $ResultRoot))
}

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

$Rows = @()
foreach ($Model in $Models) {
    $SafeModel = ConvertTo-SafeName $Model
    $Workspace = Join-Path $ResolvedWorkspaceRoot $SafeModel
    if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
        throw "Missing prepared workspace for $Model at $Workspace"
    }

    foreach ($Task in $Tasks) {
        Write-Host "" 
        Write-Host "=== $Model :: $Task ===" -ForegroundColor Cyan
        & $Python $Runner `
            --model $Model `
            --workspace-clone $Workspace `
            --task-id $Task `
            --output-root $ResolvedResultRoot `
            --command-backend $CommandBackend `
            --docker-image $DockerImage
        $Code = $LASTEXITCODE

        $TaskRoot = Join-Path (Join-Path $ResolvedResultRoot $SafeModel) $Task
        $Latest = Get-ChildItem -LiteralPath $TaskRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            Select-Object -First 1
        $ResultPath = if ($null -eq $Latest) { $null } else { Join-Path $Latest.FullName "result.json" }

        if ($null -ne $ResultPath -and (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
            $Result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
            $Rows += [pscustomobject]@{
                model = $Model
                task = $Task
                passed = $Result.passed
                stop_reason = $Result.stop_reason
                wall_time_ms = $Result.wall_time_ms
                model_turns = $Result.totals.model_turns
                tool_calls = $Result.totals.tool_calls
                authority_denials = $Result.totals.authority_denials
                test_command_calls = $Result.totals.test_command_calls
                prompt_eval_count = $Result.totals.prompt_eval_count
                eval_count = $Result.totals.eval_count
                changed_paths = @($Result.changed_paths).Count
                result_file = $ResultPath
                exit_code = $Code
            }
        }
        else {
            $Rows += [pscustomobject]@{
                model = $Model
                task = $Task
                passed = $false
                stop_reason = "result_missing"
                wall_time_ms = $null
                model_turns = $null
                tool_calls = $null
                authority_denials = $null
                test_command_calls = $null
                prompt_eval_count = $null
                eval_count = $null
                changed_paths = $null
                result_file = $ResultPath
                exit_code = $Code
            }
        }
    }

    # Preserve warm residency across this model's task battery, then unload before
    # moving to the next candidate so candidates do not compete for VRAM.
    & ollama stop $Model *> $null
}

$BatchStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$BatchDir = Join-Path $ResolvedResultRoot "batch-$BatchStamp"
New-Item -ItemType Directory -Path $BatchDir -Force | Out-Null
$Rows | Export-Csv -Path (Join-Path $BatchDir "comparison.csv") -NoTypeInformation -Encoding utf8
$Rows | ConvertTo-Json -Depth 20 | Set-Content -Path (Join-Path $BatchDir "comparison.json") -Encoding utf8

Write-Host ""
Write-Host "=== CONSTRUCTION LAB COMPARISON ===" -ForegroundColor Green
$Rows | Format-Table -AutoSize
Write-Host ""
Write-Host "Batch evidence: $BatchDir"
