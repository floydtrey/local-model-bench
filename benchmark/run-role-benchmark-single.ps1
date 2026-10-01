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
$transportJson = Join-Path $output 'transport-verification.json'
$utf8 = [Text.UTF8Encoding]::new($false)

$env:DSH_HOME = $dshHome
$env:DSH_TELEMETRY_DISABLED = '1'

$started = Get-Date
$exitCode = $null

function RemainingSeconds {
  return [math]::Floor($WallSeconds - ((Get-Date) - $started).TotalSeconds)
}

function Get-Sha256Hex([byte[]]$bytes) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
  }
  finally {
    $sha.Dispose()
  }
}

function Get-Fingerprint([string]$text) {
  $bytes = $utf8.GetBytes($text)
  return [ordered]@{
    utf16CodeUnits = $text.Length
    utf8Bytes = $bytes.Length
    sha256 = Get-Sha256Hex $bytes
  }
}

function Write-ExactUtf8([string]$path, [string]$text) {
  [IO.File]::WriteAllBytes($path, $utf8.GetBytes($text))
}

function Write-JsonUtf8([string]$path, $value) {
  $json = $value | ConvertTo-Json -Depth 12
  Write-ExactUtf8 $path $json
}

function Write-RunRecord([string]$condition, $code, $effectiveContext = $null) {
  $ended = Get-Date
  Write-JsonUtf8 $runJson ([ordered]@{
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
  })
}

function Verify-Transport([string]$nativeSessionPath) {
  $roleSentPath = Join-Path $output 'role-turn.stdin.txt'
  $intentSentPath = Join-Path $output 'intent-turn.stdin.txt'
  $roleReceivedPath = Join-Path $output 'role-turn.dsh-received.txt'
  $intentReceivedPath = Join-Path $output 'intent-turn.dsh-received.txt'

  $result = [ordered]@{
    checked = $false
    passed = $false
    nativeSession = $nativeSessionPath
    expectedUserMessages = 2
    observedUserMessages = 0
    role = $null
    intent = $null
    reason = $null
  }

  if (-not $nativeSessionPath -or -not (Test-Path -LiteralPath $nativeSessionPath)) {
    $result.reason = 'Native DSH session evidence is missing.'
    Write-JsonUtf8 $transportJson $result
    return [pscustomobject]$result
  }
  if (-not (Test-Path -LiteralPath $roleSentPath) -or -not (Test-Path -LiteralPath $intentSentPath)) {
    $result.reason = 'Exact outbound stdin evidence is missing.'
    Write-JsonUtf8 $transportJson $result
    return [pscustomobject]$result
  }

  $nativeText = [IO.File]::ReadAllText($nativeSessionPath, $utf8)
  $messages = @()

  foreach ($line in ($nativeText -split "\r?\n")) {
    if (-not $line.Trim()) { continue }
    try {
      $event = $line | ConvertFrom-Json
    } catch {
      continue
    }

    if ($event.type -ne 'user/message') { continue }
    if ($event.data.role -ne 'user') { continue }
    if ($event.data.source.kind -ne 'user') { continue }

    $blocks = @($event.data.content)
    $shapeValid = $blocks.Count -eq 1 -and $blocks[0].type -eq 'text' -and $null -ne $blocks[0].text
    $text = if ($shapeValid) { [string]$blocks[0].text } else { $null }
    $messages += [pscustomobject]@{
      shapeValid = $shapeValid
      text = $text
      seq = $event.seq
    }
  }

  $result.checked = $true
  $result.observedUserMessages = $messages.Count

  $roleExpected = [IO.File]::ReadAllText($roleSentPath, $utf8)
  $intentExpected = [IO.File]::ReadAllText($intentSentPath, $utf8)

  if ($messages.Count -ge 1 -and $messages[0].shapeValid) {
    Write-ExactUtf8 $roleReceivedPath $messages[0].text
    $roleMatch = [string]::Equals($roleExpected, $messages[0].text, [StringComparison]::Ordinal)
    $result.role = [ordered]@{
      sequence = $messages[0].seq
      sentPath = $roleSentPath
      receivedPath = $roleReceivedPath
      sent = Get-Fingerprint $roleExpected
      received = Get-Fingerprint $messages[0].text
      exactMatch = $roleMatch
    }
  } else {
    $result.role = [ordered]@{ exactMatch = $false; reason = 'First user-origin message is missing or is not exactly one text block.' }
  }

  if ($messages.Count -ge 2 -and $messages[1].shapeValid) {
    Write-ExactUtf8 $intentReceivedPath $messages[1].text
    $intentMatch = [string]::Equals($intentExpected, $messages[1].text, [StringComparison]::Ordinal)
    $result.intent = [ordered]@{
      sequence = $messages[1].seq
      sentPath = $intentSentPath
      receivedPath = $intentReceivedPath
      sent = Get-Fingerprint $intentExpected
      received = Get-Fingerprint $messages[1].text
      exactMatch = $intentMatch
    }
  } else {
    $result.intent = [ordered]@{ exactMatch = $false; reason = 'Second user-origin message is missing or is not exactly one text block.' }
  }

  $result.passed = (
    $messages.Count -eq 2 -and
    $result.role.exactMatch -eq $true -and
    $result.intent.exactMatch -eq $true
  )

  if (-not $result.passed) {
    $result.reason = 'Runner-to-DSH transport did not preserve both user messages exactly.'
  }

  Write-JsonUtf8 $transportJson $result
  return [pscustomobject]$result
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

  $obs = $null
  $nativeSessionPath = $null
  if (Test-Path -LiteralPath $obsJson) {
    $obs = [IO.File]::ReadAllText($obsJson, $utf8) | ConvertFrom-Json
    $nativeSessionPath = $obs.evidence.nativeSession
  }
  $transport = Verify-Transport $nativeSessionPath

  $psState = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/ps' -TimeoutSec 5
  Write-JsonUtf8 $ollamaPsJson $psState
  $loaded = @($psState.models) | Where-Object { $_.name -eq $ModelId } | Select-Object -First 1
  $effectiveContext = if ($null -ne $loaded) { [int64]$loaded.context_length } else { $null }

  $terminal = if ($exitCode -eq 124) { 'wall_clock' } elseif ($exitCode -eq 0) { 'completed' } else { 'runtime_error' }

  if ($exitCode -eq 0 -and -not $transport.passed) {
    $terminal = 'transport_error'
    $exitCode = 5
  } elseif ($terminal -eq 'completed' -and $effectiveContext -ne $ExpectedContextWindow) {
    $terminal = 'runtime_configuration_error'
    $exitCode = 4
  }

  if (Test-Path -LiteralPath $runJson) {
    $record = [IO.File]::ReadAllText($runJson, $utf8) | ConvertFrom-Json
    $record | Add-Member -NotePropertyName terminalCondition -NotePropertyValue $terminal -Force
    $record | Add-Member -NotePropertyName dshExitCode -NotePropertyValue $exitCode -Force
    $record | Add-Member -NotePropertyName runtimeKind -NotePropertyValue $RuntimeKind -Force
    $record | Add-Member -NotePropertyName modelId -NotePropertyValue $ModelId -Force
    $record | Add-Member -NotePropertyName expectedContextWindow -NotePropertyValue $ExpectedContextWindow -Force
    $record | Add-Member -NotePropertyName effectiveContextWindow -NotePropertyValue $effectiveContext -Force
    $record | Add-Member -NotePropertyName candidatePatch -NotePropertyValue $candidate -Force
    $record | Add-Member -NotePropertyName rolePrompt -NotePropertyValue $role -Force
    $record | Add-Member -NotePropertyName package -NotePropertyValue $package -Force
    $record | Add-Member -NotePropertyName dshSettingsSnapshot -NotePropertyValue (Join-Path $output 'dsh-settings.yaml') -Force
    $record | Add-Member -NotePropertyName ollamaPsSnapshot -NotePropertyValue $ollamaPsJson -Force
    $record | Add-Member -NotePropertyName transportVerification -NotePropertyValue $transportJson -Force
    $record | Add-Member -NotePropertyName transportPassed -NotePropertyValue ([bool]$transport.passed) -Force

    if ($null -ne $obs) {
      $nativeStop = $null
      if ($obs.sessions -and $obs.sessions.Count -eq 1) { $nativeStop = $obs.sessions[0].turnEndReason }
      $record | Add-Member -NotePropertyName nativeDshStopReason -NotePropertyValue $nativeStop -Force
      $record | Add-Member -NotePropertyName reasoningCaptured -NotePropertyValue ([bool]$obs.reasoningCapturedInSession) -Force
      $record | Add-Member -NotePropertyName nativeSessionEvidence -NotePropertyValue $obs.evidence.nativeSession -Force
      $record | Add-Member -NotePropertyName reasoningFile -NotePropertyValue $obs.evidence.reasoning -Force
      $record | Add-Member -NotePropertyName finalFile -NotePropertyValue $obs.evidence.final -Force
    }

    Write-JsonUtf8 $runJson $record
  } else {
    Write-RunRecord $terminal $exitCode $effectiveContext
  }

  if ($terminal -eq 'transport_error') {
    Write-Host "Transport verification FAILED. Evidence: $transportJson"
  } elseif ($terminal -eq 'runtime_configuration_error') {
    Write-Host "Effective Ollama context mismatch: expected $ExpectedContextWindow, observed $effectiveContext."
  } elseif ($transport.passed) {
    Write-Host "Transport verification: PASS (exact runner-to-DSH match for both turns)"
  }

  exit $exitCode
}
catch {
  Write-Host $_
  if (-not (Test-Path -LiteralPath $runJson)) { Write-RunRecord 'runtime_error' $null }
  exit 3
}
