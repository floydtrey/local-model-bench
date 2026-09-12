param(
    [Parameter(Mandatory = $true)]
    [string[]]$Models,

    [string[]]$Tasks = @(
        "repair-calculator-average",
        "add-json-report",
        "remove-legacy-mode"
    ),

    [Parameter(Mandatory = $true)]
    [string]$RoundLabel,

    [string]$WorkspaceRoot = "local-state/construction-lab/workspaces",

    [string]$ResultRoot = "local-state/construction-lab/runs",

    [ValidateSet("ollama", "openai_compatible")]
    [string]$Provider = "ollama",

    [string]$ToolProfile,

    [string]$BaseUrl = "http://127.0.0.1:11434",

    [string]$ApiKeyEnv,

    [string]$ProviderProvenanceFile,

    [string]$CommandBackend = "docker",

    [string]$DockerImage = "python:3.12-slim"
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

function New-UniqueDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Stem
    )

    New-Item -ItemType Directory -Path $Parent -Force | Out-Null
    for ($Suffix = 0; $Suffix -lt 10000; $Suffix++) {
        $Name = if ($Suffix -eq 0) { $Stem } else { "{0}-{1:D2}" -f $Stem, $Suffix }
        $Candidate = Join-Path $Parent $Name
        try {
            New-Item -ItemType Directory -Path $Candidate -ErrorAction Stop | Out-Null
            return $Candidate
        }
        catch {
            if (Test-Path -LiteralPath $Candidate) {
                continue
            }
            throw
        }
    }
    throw "Unable to allocate a unique evidence directory under $Parent."
}

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $Here)
$Runner = Join-Path $Here "run-construction-task.py"
$TelemetryScript = Join-Path $Here "capture-construction-telemetry.ps1"

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
$SafeRound = Get-RoundName $RoundLabel
$RoundWorkspaceRoot = Resolve-ContainedChild $ResolvedWorkspaceRoot $SafeRound
$RoundResultRoot = Resolve-ContainedChild $ResolvedResultRoot $SafeRound

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
$OllamaPath = if ($Provider -eq "ollama") {
    (Get-Command ollama -ErrorAction Stop).Source
}
else {
    $null
}
if ($Provider -eq "openai_compatible" -and [string]::IsNullOrWhiteSpace($ToolProfile)) {
    throw "ToolProfile is required for openai_compatible Construction runs."
}
if ($Provider -eq "ollama" -and -not [string]::IsNullOrWhiteSpace($ToolProfile) -and $ToolProfile -ne "openai_native") {
    throw "Ollama Construction runs remain native-only."
}

if (-not (Test-Path -LiteralPath $TelemetryScript -PathType Leaf)) {
    throw "Construction telemetry sampler is missing: $TelemetryScript"
}

$TelemetryStaging = Join-Path $RoundResultRoot ".telemetry-staging"
New-Item -ItemType Directory -Path $TelemetryStaging -Force | Out-Null

$Rows = @()
$WorkspaceProvenance = @()
foreach ($Model in $Models) {
    $SafeModel = ConvertTo-SafeName $Model
    if ([string]::IsNullOrWhiteSpace($SafeModel) -or $SafeModel -in @(".", "..")) {
        throw "Model name does not produce a safe workspace directory name: $Model"
    }
    $Workspace = Resolve-ContainedChild $RoundWorkspaceRoot $SafeModel
    if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
        throw "Missing prepared workspace for $Model at $Workspace"
    }
    $WorkspaceMarker = Join-Path $Workspace ".construction-lab-workspace.json"
    if (-not (Test-Path -LiteralPath $WorkspaceMarker -PathType Leaf)) {
        throw "Workspace is not a marked disposable Construction Lab clone: $Workspace"
    }
    $WorkspaceMetadata = Get-Content -LiteralPath $WorkspaceMarker -Raw | ConvertFrom-Json
    if (
        $WorkspaceMetadata.model -ne $Model -or
        $WorkspaceMetadata.safe_model -ne $SafeModel -or
        $WorkspaceMetadata.round_label -ne $RoundLabel -or
        [System.IO.Path]::GetFullPath([string]$WorkspaceMetadata.workspace) -ne [System.IO.Path]::GetFullPath($Workspace)
    ) {
        throw "Workspace marker does not match model, round, and path: $Workspace"
    }
    $WorkspaceCommit = (& git -C $Workspace rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $WorkspaceCommit -ne $WorkspaceMetadata.fixture_commit) {
        throw "Workspace HEAD does not match its prepared fixture commit: $Workspace"
    }
    $WorkspaceStatus = @(
        & git -C $Workspace status --porcelain=v1 --untracked-files=all
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to verify clean fixture workspace: $Workspace"
    }
    $WorkspaceChanges = @(
        $WorkspaceStatus | Where-Object { $_ -ne "?? .construction-lab-workspace.json" }
    )
    if ($WorkspaceChanges.Count -gt 0) {
        throw "Workspace is not fresh for $Model. Reprepare this round with -Reset before running."
    }
    $WorkspaceProvenance += $WorkspaceMetadata

    foreach ($Task in $Tasks) {
        Write-Host ""
        Write-Host "=== $Model :: $Task ===" -ForegroundColor Cyan

        $TelemetryId = [guid]::NewGuid().ToString("N")
        $TelemetryCsv = Join-Path $TelemetryStaging "$TelemetryId.csv"
        $TelemetryStop = Join-Path $TelemetryStaging "$TelemetryId.stop"
        $RunDirectoryFile = Join-Path $TelemetryStaging "$TelemetryId.run-directory.txt"
        New-Item -ItemType File -Path $TelemetryStop -Force | Out-Null
        $TelemetryJob = Start-Job `
            -FilePath $TelemetryScript `
            -ArgumentList @($TelemetryCsv, $TelemetryStop, 2.0)

        try {
            $Code = 1
            $RunnerArgs = @(
                $Runner,
                "--model", $Model,
                "--provider", $Provider,
                "--base-url", $BaseUrl,
                "--workspace-clone", $Workspace,
                "--task-id", $Task,
                "--output-root", $RoundResultRoot,
                "--round-label", $RoundLabel,
                "--run-directory-file", $RunDirectoryFile,
                "--command-backend", $CommandBackend,
                "--docker-image", $DockerImage
            )
            if (-not [string]::IsNullOrWhiteSpace($ToolProfile)) {
                $RunnerArgs += @("--tool-profile", $ToolProfile)
            }
            if (-not [string]::IsNullOrWhiteSpace($ApiKeyEnv)) {
                $RunnerArgs += @("--api-key-env", $ApiKeyEnv)
            }
            if (-not [string]::IsNullOrWhiteSpace($ProviderProvenanceFile)) {
                $RunnerArgs += @("--provider-provenance-file", $ProviderProvenanceFile)
            }
            & $Python @RunnerArgs
            $Code = $LASTEXITCODE
        }
        finally {
            Remove-Item -LiteralPath $TelemetryStop -Force -ErrorAction SilentlyContinue
            Wait-Job -Job $TelemetryJob -Timeout 15 | Out-Null
            Receive-Job -Job $TelemetryJob -ErrorAction SilentlyContinue | Out-Null
            Remove-Job -Job $TelemetryJob -Force -ErrorAction SilentlyContinue
        }

        $TaskRoot = Resolve-ContainedChild (Resolve-ContainedChild $RoundResultRoot $SafeModel) $Task
        $RunDirectory = if (Test-Path -LiteralPath $RunDirectoryFile -PathType Leaf) {
            [System.IO.Path]::GetFullPath((Get-Content -LiteralPath $RunDirectoryFile -Raw).Trim())
        }
        else {
            $null
        }
        Remove-Item -LiteralPath $RunDirectoryFile -Force -ErrorAction SilentlyContinue
        if ($null -ne $RunDirectory) {
            $TaskPrefix = [System.IO.Path]::GetFullPath($TaskRoot).TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            ) + [System.IO.Path]::DirectorySeparatorChar
            if (-not $RunDirectory.StartsWith($TaskPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Runner returned an evidence directory outside the expected task root: $RunDirectory"
            }
        }
        $ResultPath = if ($null -eq $RunDirectory) { $null } else { Join-Path $RunDirectory "result.json" }
        $TelemetryPath = if ($null -eq $RunDirectory) { $null } else { Join-Path $RunDirectory "telemetry.csv" }

        if (
            $null -ne $TelemetryPath -and
            (Test-Path -LiteralPath $TelemetryCsv -PathType Leaf)
        ) {
            Move-Item -LiteralPath $TelemetryCsv -Destination $TelemetryPath -ErrorAction Stop
        }
        else {
            Remove-Item -LiteralPath $TelemetryCsv -Force -ErrorAction SilentlyContinue
        }

        if ($null -ne $ResultPath -and (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
            $Result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
            $Rows += [pscustomobject]@{
                model = $Model
                provider = $Provider
                tool_profile = $Result.configuration.tool_profile
                execution_interface_sha256 = $Result.execution_interface.sha256
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
                telemetry_file = if ($null -ne $TelemetryPath -and (Test-Path -LiteralPath $TelemetryPath)) { $TelemetryPath } else { $null }
                result_file = $ResultPath
                exit_code = $Code
            }
        }
        else {
            $Rows += [pscustomobject]@{
                model = $Model
                provider = $Provider
                tool_profile = $ToolProfile
                execution_interface_sha256 = $null
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
                telemetry_file = $TelemetryPath
                result_file = $ResultPath
                exit_code = $Code
            }
        }
    }

    # Preserve warm residency across this model's task battery, then unload before
    # moving to the next candidate so candidates do not compete for VRAM. Model
    # unload is cleanup only: stderr/noisy output or a non-zero stop exit must never
    # abort the remaining benchmark candidates.
    if ($Provider -eq "ollama") {
      try {
        $StopProcess = Start-Process `
            -FilePath $OllamaPath `
            -ArgumentList @("stop", $Model) `
            -NoNewWindow `
            -Wait `
            -PassThru
        if ($StopProcess.ExitCode -ne 0) {
            Write-Warning "ollama stop returned exit code $($StopProcess.ExitCode) for $Model; continuing batch."
        }
      }
      catch {
        Write-Warning "Unable to unload $Model after its task battery: $($_.Exception.Message). Continuing batch."
      }
    }
}

$BatchStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$BatchDir = New-UniqueDirectory -Parent $RoundResultRoot -Stem ("batch-" + $BatchStamp)
$Rows | Export-Csv -Path (Join-Path $BatchDir "comparison.csv") -NoTypeInformation -Encoding utf8
$Rows | ConvertTo-Json -Depth 20 | Set-Content -Path (Join-Path $BatchDir "comparison.json") -Encoding utf8
[ordered]@{
    schema_version = "construction-lab-batch:v2"
    round_label = $RoundLabel
    model_order = @($Models)
    task_order = @($Tasks)
    provider = $Provider
    tool_profile = if ([string]::IsNullOrWhiteSpace($ToolProfile)) { "openai_native" } else { $ToolProfile }
    base_url = $BaseUrl
    api_key_env = $ApiKeyEnv
    provider_provenance_file = $ProviderProvenanceFile
    workspace_root = $RoundWorkspaceRoot
    result_root = $RoundResultRoot
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    workspaces = @($WorkspaceProvenance)
} | ConvertTo-Json -Depth 20 | Set-Content -Path (Join-Path $BatchDir "batch-manifest.json") -Encoding utf8

Write-Host ""
Write-Host "=== CONSTRUCTION LAB COMPARISON ===" -ForegroundColor Green
$Rows | Format-Table -AutoSize
Write-Host ""
Write-Host "Batch evidence: $BatchDir"
