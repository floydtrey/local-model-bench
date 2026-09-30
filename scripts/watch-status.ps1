param(
    [string]$Run = "",
    [int]$RefreshSeconds = 2,
    [int]$QuietWarningSeconds = 30,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ($RefreshSeconds -lt 1) { throw "RefreshSeconds must be at least 1." }
if ($QuietWarningSeconds -lt 1) { throw "QuietWarningSeconds must be at least 1." }

if ($Run) {
    $RunPath = if ([System.IO.Path]::IsPathRooted($Run)) { $Run } else { Join-Path $ProjectRoot $Run }
} else {
    $LatestManifest = Get-ChildItem -Path (Join-Path $ProjectRoot "results") -Filter "manifest.json" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $LatestManifest) { throw "No benchmark run was found. Start a run first or pass -Run with its result folder." }
    $RunPath = Split-Path -Parent $LatestManifest.FullName
}

$ManifestPath = Join-Path $RunPath "manifest.json"
$CheckpointPath = Join-Path $RunPath "checkpoint.json"
$TerminalStates = @("completed", "completed_with_errors", "wall_clock_exhausted", "interrupted", "failed")

while (-not (Test-Path -LiteralPath $ManifestPath)) {
    Clear-Host
    Write-Host "LOCAL MODEL BENCH"
    Write-Host "Waiting for the run to initialize..."
    if ($Once) { throw "The run has not initialized yet: $RunPath" }
    Start-Sleep -Seconds $RefreshSeconds
}

do {
    $Now = [DateTimeOffset]::UtcNow
    $Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
    $Checkpoint = if (Test-Path -LiteralPath $CheckpointPath) {
        Get-Content -Raw -LiteralPath $CheckpointPath | ConvertFrom-Json
    } else { $null }

    $Completed = if ($Checkpoint) { [int]$Checkpoint.progress.completed } else { 0 }
    $Total = if ($Checkpoint) { [int]$Checkpoint.progress.total } else { 0 }
    $Percent = if ($Checkpoint) { [double]$Checkpoint.progress.percent } else { 0 }

    $StartedAt = [DateTimeOffset]::Parse([string]$Manifest.started_at)
    $Elapsed = $Now - $StartedAt
    $LastUpdateAge = if ($Checkpoint) {
        $Now - [DateTimeOffset]::Parse([string]$Checkpoint.last_updated_at)
    } else { $Elapsed }

    $CurrentText = "initializing"
    if ($Checkpoint -and $Checkpoint.current) {
        $CurrentText = "$($Checkpoint.current.model_id) | $($Checkpoint.current.suite_id)/$($Checkpoint.current.case_id)"
    } elseif ($TerminalStates -contains $Manifest.status) {
        $CurrentText = [string]$Manifest.status
    }

    $BoundaryText = "not configured"
    $DeadlineAt = $null
    if ($Checkpoint -and $Checkpoint.wall_clock -and $Checkpoint.wall_clock.deadline_at) {
        $DeadlineAt = [DateTimeOffset]::Parse([string]$Checkpoint.wall_clock.deadline_at)
    } elseif ($Manifest.wall_clock -and $Manifest.wall_clock.deadline_at) {
        $DeadlineAt = [DateTimeOffset]::Parse([string]$Manifest.wall_clock.deadline_at)
    }
    if ($DeadlineAt) {
        $BoundaryRemaining = $DeadlineAt - $Now
        if ($BoundaryRemaining.TotalSeconds -gt 0) {
            $BoundaryText = "{0:hh\:mm\:ss} remaining" -f $BoundaryRemaining
        } else {
            $BoundaryText = "reached {0:hh\:mm\:ss} ago" -f $BoundaryRemaining.Negate()
        }
    }

    $Activity = if ($TerminalStates -contains $Manifest.status) {
        "terminal"
    } elseif ($LastUpdateAge.TotalSeconds -ge $QuietWarningSeconds) {
        "quiet: no new checkpoint; execution state is unknown (not classified stalled)"
    } else {
        "recent checkpoint"
    }

    Clear-Host
    Write-Host "LOCAL MODEL BENCH"
    Write-Host ("Run:       {0}" -f $Manifest.run_id)
    Write-Host ("Status:    {0}" -f $Manifest.status)
    Write-Host ("Current:   {0}" -f $CurrentText)
    Write-Host ("Progress:  {0}/{1} ({2:N1}%)" -f $Completed, $Total, $Percent)
    Write-Host ("Elapsed:   {0:hh\:mm\:ss}" -f $Elapsed)
    Write-Host ("Boundary:  {0}" -f $BoundaryText)
    Write-Host ("Activity:  {0}; checkpoint age {1:N0}s" -f $Activity, $LastUpdateAge.TotalSeconds)
    Write-Host ("Evidence:  {0}" -f $RunPath)

    if ($TerminalStates -contains $Manifest.status -or $Once) { break }
    Start-Sleep -Seconds $RefreshSeconds
} while ($true)
