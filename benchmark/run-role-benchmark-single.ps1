param(
  [Parameter(Mandatory=$true)][string]$CandidatePatch,
  [Parameter(Mandatory=$true)][ValidateSet('ollama')][string]$RuntimeKind,
  [Parameter(Mandatory=$true)][string]$ModelId,
  [Parameter(Mandatory=$true)][int]$ExpectedContextWindow,
  [Parameter(Mandatory=$true)][string]$RolePrompt,
  [Parameter(Mandatory=$true)][string]$PackageFile,
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [int]$WallSeconds = 600
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$settingsFile = Join-Path $dshHome 'settings.yaml'
$observer = Join-Path $repo 'benchmark\dsh\passive-observer.mjs'
$dshRunner = Join-Path $repo 'benchmark\dsh\run-single-dsh.ps1'

$candidate = (Resolve-Path $CandidatePatch).Path
$role = (Resolve-Path $RolePrompt).Path
$package = (Resolve-Path $PackageFile).Path
$output = [IO.Path]::GetFullPath($OutputDir)

foreach ($required in @($dsh,$basePatch,$observer,$dshRunner,$settingsFile)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}
if (Test-Path -LiteralPath $output) { throw "Output directory already exists: $output" }
if ($WallSeconds -lt 1) { throw 'WallSeconds must be at least 1.' }
if ($ExpectedContextWindow -lt 1) { throw 'ExpectedContextWindow must be at least 1.' }

New-Item -ItemType Directory -Path $output -Force | Out-Null
Copy-Item -LiteralPath $candidate -Destination (Join-Path $output 'candidate-patch.yml')
Copy-Item -LiteralPath $role -Destination (Join-Path $output 'role-prompt.txt')
Copy-Item -LiteralPath $package -Destination (Join-Path $output 'package.txt')
Copy-Item -LiteralPath $settingsFile -Destination (Join-Path $output 'dsh-settings.yaml')

$obsState = Join-Path $output 'observer-state.json'
$obsJson = Join-Path $output 'observations.json'
$runJson = Join-Path $output 'run.json'
$ollamaPsJson = Join-Path $output 'ollama-ps.json'

$env:DSH_HOME = $dshHome
$env:DSH_TELEMETRY_DISABLED = '1'

$started = Get-Date
$exitCode = $null

function RemainingSeconds {
  return [math]::Floor($WallSeconds - ((Get-Date) - $started).TotalSeconds)
}

function Write-RunRecord([string]$condition, $code, $effectiveContext = $null) {
  $ended = Get-Date
  [ordered]@{
    startedAt = $started.ToString('o')
    endedAt = $ended.ToString('o')
    wallClockSeconds = [math]::Round(($ended-$started).TotalSeconds,3)
    configuredWallClockSeconds = $WallSeconds
    dshExitCode = $code
    terminalCondition = $condition
    runtimeKind = $RuntimeKind
    modelId = $ModelId
    expectedContextWindow = $ExpectedContextWindow
    effectiveContextWindow = $effectiveContext
    candidatePatch = $candidate
    rolePrompt = $role
    package = $package
    dshSettingsSnapshot = (Join-Path $output 'dsh-settings.yaml')
  } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runJson -Encoding UTF8
}

try {
  try {
    $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
  } catch {
    throw 'Persistent Ollama service is not reachable at http://127.0.0.1:11434. Start Ollama before the benchmark.'
  }

  if ($tags.models.name -notcontains $ModelId) { throw "Required Ollama model is not installed: $ModelId" }

  $dump = (& $dsh --profile headless --dump-config 2>&1 | Out-String)
  if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the DSH headless profile.' }
  if ($dump -notmatch '@zhangyi/dsh-llm-ollama') {
    throw 'Native Ollama plugin is not installed for DSH headless. Run: dsh plugin --profile headless add git+https://github.com/1035041186/dsh-llm-ollama.git'
  }

  if ((RemainingSeconds) -le 0) { Write-RunRecord 'wall_clock' $null; exit 124 }

  & node.exe $observer before $obsState $dshHome
  if ($LASTEXITCODE -ne 0) { throw 'Failed to snapshot pre-run DSH state.' }

  Write-Host ''
  Write-Host 'Role Qualification v1 - single run'
  Write-Host 'Runtime:    persistent native Ollama'
  Write-Host "Model:      $ModelId"
  Write-Host "Expected context: $ExpectedContextWindow"
  Write-Host "Role:       $role"
  Write-Host "Package:    $package"
  Write-Host "Output:     $output"
  Write-Host "Wall clock: $WallSeconds seconds total"
  Write-Host ''

  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $dshRunner -DshPath $dsh -BasePatch $basePatch -CandidatePatch $candidate -RolePrompt $role -PackageFile $package -WallSeconds $WallSeconds -RunJson $runJson -RunStartedAt $started
  $exitCode = $LASTEXITCODE

  & node.exe $observer after $obsState $dshHome $obsJson $exitCode
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Passive post-run observation failed.' }

  $psState = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/ps' -TimeoutSec 5
  $psState | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ollamaPsJson -Encoding UTF8
  $loaded = @($psState.models) | Where-Object { $_.name -eq $ModelId } | Select-Object -First 1
  $effectiveContext = if ($null -ne $loaded) { [int64]$loaded.context_length } else { $null }

  $terminal = if ($exitCode -eq 124) { 'wall_clock' } elseif ($exitCode -eq 0) { 'completed' } else { 'runtime_error' }
  if ($terminal -eq 'completed' -and $effectiveContext -ne $ExpectedContextWindow) {
    $terminal = 'runtime_configuration_error'
    $exitCode = 4
  }

  if (Test-Path -LiteralPath $runJson) {
    $record = Get-Content -LiteralPath $runJson -Raw | ConvertFrom-Json
    $record | Add-Member -NotePropertyName terminalCondition -NotePropertyValue $terminal -Force
    $record | Add-Member -NotePropertyName runtimeKind -NotePropertyValue $RuntimeKind -Force
    $record | Add-Member -NotePropertyName modelId -NotePropertyValue $ModelId -Force
    $record | Add-Member -NotePropertyName expectedContextWindow -NotePropertyValue $ExpectedContextWindow -Force
    $record | Add-Member -NotePropertyName effectiveContextWindow -NotePropertyValue $effectiveContext -Force
    $record | Add-Member -NotePropertyName candidatePatch -NotePropertyValue $candidate -Force
    $record | Add-Member -NotePropertyName rolePrompt -NotePropertyValue $role -Force
    $record | Add-Member -NotePropertyName package -NotePropertyValue $package -Force
    $record | Add-Member -NotePropertyName dshSettingsSnapshot -NotePropertyValue (Join-Path $output 'dsh-settings.yaml') -Force
    $record | Add-Member -NotePropertyName ollamaPsSnapshot -NotePropertyValue $ollamaPsJson -Force
    if (Test-Path -LiteralPath $obsJson) {
      $obs = Get-Content -LiteralPath $obsJson -Raw | ConvertFrom-Json
      $nativeStop = $null
      if ($obs.sessions -and $obs.sessions.Count -eq 1) { $nativeStop = $obs.sessions[0].turnEndReason }
      $record | Add-Member -NotePropertyName nativeDshStopReason -NotePropertyValue $nativeStop -Force
      $record | Add-Member -NotePropertyName reasoningCaptured -NotePropertyValue ([bool]$obs.reasoningCapturedInSession) -Force
      $record | Add-Member -NotePropertyName nativeSessionEvidence -NotePropertyValue $obs.evidence.nativeSession -Force
      $record | Add-Member -NotePropertyName reasoningFile -NotePropertyValue $obs.evidence.reasoning -Force
      $record | Add-Member -NotePropertyName finalFile -NotePropertyValue $obs.evidence.final -Force
    }
    $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runJson -Encoding UTF8
  } else {
    Write-RunRecord $terminal $exitCode $effectiveContext
  }

  if ($terminal -eq 'runtime_configuration_error') {
    Write-Error "Effective Ollama context mismatch: expected $ExpectedContextWindow, observed $effectiveContext."
  }

  exit $exitCode
}
catch {
  Write-Error $_
  if (-not (Test-Path -LiteralPath $runJson)) { Write-RunRecord 'runtime_error' $null }
  exit 3
}