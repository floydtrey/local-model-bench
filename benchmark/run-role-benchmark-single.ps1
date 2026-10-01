param(
  [Parameter(Mandatory=$true)][string]$CandidatePatch,
  [Parameter(Mandatory=$true)][ValidateSet('ollama')][string]$RuntimeKind,
  [Parameter(Mandatory=$true)][string]$ModelId,
  [Parameter(Mandatory=$true)][string]$RolePrompt,
  [Parameter(Mandatory=$true)][string]$PackageFile,
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [int]$WallSeconds = 600
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$dshHome = Join-Path $repo 'local-state\role-qualification-v1\dsh-home'
$observer = Join-Path $repo 'benchmark\dsh\passive-observer.mjs'
$dshRunner = Join-Path $repo 'benchmark\dsh\run-single-dsh.ps1'

$candidate = (Resolve-Path $CandidatePatch).Path
$role = (Resolve-Path $RolePrompt).Path
$package = (Resolve-Path $PackageFile).Path
$output = [IO.Path]::GetFullPath($OutputDir)

foreach ($required in @($dsh,$basePatch,$observer,$dshRunner)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}
if (Test-Path -LiteralPath $output) { throw "Output directory already exists: $output" }
if ($WallSeconds -lt 1) { throw 'WallSeconds must be at least 1.' }

New-Item -ItemType Directory -Path $output -Force | Out-Null
Copy-Item -LiteralPath $candidate -Destination (Join-Path $output 'candidate-patch.yml')
Copy-Item -LiteralPath $role -Destination (Join-Path $output 'role-prompt.txt')
Copy-Item -LiteralPath $package -Destination (Join-Path $output 'package.txt')
New-Item -ItemType Directory -Path $dshHome -Force | Out-Null

$obsState = Join-Path $output 'observer-state.json'
$obsJson = Join-Path $output 'observations.json'
$runJson = Join-Path $output 'run.json'
$ollamaPidFile = Join-Path $output 'ollama.pid'

$env:DSH_HOME = $dshHome
$env:DSH_TELEMETRY_DISABLED = '1'
$env:ROLE_BENCHMARK_LOCAL_KEY = 'local-benchmark-placeholder'

$started = Get-Date
$startedOllama = $false
$ollamaProcess = $null
$terminal = 'runtime_error'
$exitCode = $null

function RemainingSeconds {
  return [math]::Floor($WallSeconds - ((Get-Date) - $started).TotalSeconds)
}

function Write-RunRecord([string]$condition, $code) {
  $ended = Get-Date
  [ordered]@{
    startedAt = $started.ToString('o')
    endedAt = $ended.ToString('o')
    wallClockSeconds = [math]::Round(($ended-$started).TotalSeconds,3)
    configuredWallClockSeconds = $WallSeconds
    dshExitCode = $code
    terminalCondition = $condition
    runnerStartedOllama = $startedOllama
    runtimeKind = $RuntimeKind
    modelId = $ModelId
    candidatePatch = $candidate
    rolePrompt = $role
    package = $package
  } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $runJson -Encoding UTF8
}

try {
  $ollama = (Get-Command ollama.exe -ErrorAction Stop).Source

  $apiReady = $false
  try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
    $apiReady = $true
  } catch {}

  if (-not $apiReady) {
    Write-Host 'Ollama API is offline. Starting a temporary Ollama server...'
    $ollamaProcess = Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru
    $ollamaProcess.Id | Set-Content -LiteralPath $ollamaPidFile -NoNewline
    $startedOllama = $true

    Write-Host 'Waiting for Ollama API...'
    while ((RemainingSeconds) -gt 0) {
      try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
        $apiReady = $true
        break
      } catch {
        Start-Sleep -Milliseconds 500
      }
    }
    if (-not $apiReady) {
      $terminal = 'wall_clock'
      Write-RunRecord $terminal $null
      exit 124
    }
  } else {
    Write-Host 'Ollama API is already running. It will be left running.'
  }

  if ((RemainingSeconds) -le 0) {
    Write-RunRecord 'wall_clock' $null
    exit 124
  }

  $timeoutForTags = [math]::Max(1,[math]::Min(5,(RemainingSeconds)))
  $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec $timeoutForTags
  if ($tags.models.name -notcontains $ModelId) {
    throw "Required Ollama model is not installed: $ModelId"
  }

  & node.exe $observer before $obsState $dshHome
  if ($LASTEXITCODE -ne 0) { throw 'Failed to snapshot pre-run DSH state.' }

  Write-Host ''
  Write-Host 'Role Qualification v1 - single run'
  Write-Host "Runtime:    $RuntimeKind"
  Write-Host "Model:      $ModelId"
  Write-Host "Role:       $role"
  Write-Host "Package:    $package"
  Write-Host "Output:     $output"
  Write-Host "Wall clock: $WallSeconds seconds total, including runtime startup"
  Write-Host ''

  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $dshRunner -DshPath $dsh -BasePatch $basePatch -CandidatePatch $candidate -RolePrompt $role -PackageFile $package -WallSeconds $WallSeconds -RunJson $runJson -RunStartedAt $started
  $exitCode = $LASTEXITCODE

  if (Test-Path -LiteralPath $runJson) {
    $record = Get-Content -LiteralPath $runJson -Raw | ConvertFrom-Json
    $record | Add-Member -NotePropertyName runnerStartedOllama -NotePropertyValue $startedOllama -Force
    $record | Add-Member -NotePropertyName runtimeKind -NotePropertyValue $RuntimeKind -Force
    $record | Add-Member -NotePropertyName modelId -NotePropertyValue $ModelId -Force
    $record | Add-Member -NotePropertyName candidatePatch -NotePropertyValue $candidate -Force
    $record | Add-Member -NotePropertyName rolePrompt -NotePropertyValue $role -Force
    $record | Add-Member -NotePropertyName package -NotePropertyValue $package -Force
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $runJson -Encoding UTF8
  } else {
    $condition = if ($exitCode -eq 124) { 'wall_clock' } elseif ($exitCode -eq 0) { 'completed' } else { 'runtime_error' }
    Write-RunRecord $condition $exitCode
  }

  & node.exe $observer after $obsState $dshHome $obsJson $exitCode
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Passive post-run observation failed.' }

  exit $exitCode
}
catch {
  Write-Error $_
  if (-not (Test-Path -LiteralPath $runJson)) { Write-RunRecord 'runtime_error' $null }
  exit 3
}
finally {
  if ($startedOllama -and $ollamaProcess) {
    Write-Host 'Stopping temporary Ollama server started by this launcher...'
    Stop-Process -Id $ollamaProcess.Id -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ollamaPidFile -Force -ErrorAction SilentlyContinue
  }
}
