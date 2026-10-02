param(
  [string]$OutputDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\session-persistence-v1\test-01'),
  [int]$WallSecondsPerTurn = 180
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$ollama = (Get-Command ollama.exe -ErrorAction Stop).Source
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$primaryPatch = Join-Path $repo 'benchmark\dsh\smoke-qwen35-9b.patch.yml'
$alternatePatch = Join-Path $repo 'benchmark\session-persistence\alternate-llama32-1b.patch.yml'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$sessionRoot = Join-Path $dshHome 'benchmark-sessions'
$primaryModel = 'qwen3.5:9b'
$alternateModel = 'llama3.2:1b'
$utf8 = [Text.UTF8Encoding]::new($false)

foreach ($required in @($dsh,$ollama,$basePatch,$primaryPatch,$alternatePatch)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required path: $required" }
}
if ($WallSecondsPerTurn -lt 10) { throw 'WallSecondsPerTurn must be at least 10.' }

$output = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) { throw "Output directory already exists: $output" }
New-Item -ItemType Directory -Path $output -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $output 'turns') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $output 'sessions') -Force | Out-Null

$env:DSH_HOME = $dshHome
$env:DSH_TELEMETRY_DISABLED = '1'

function Write-Utf8([string]$Path,[string]$Text) {
  [IO.File]::WriteAllBytes($Path,$utf8.GetBytes($Text))
}

function Write-Json([string]$Path,$Value) {
  Write-Utf8 $Path ($Value | ConvertTo-Json -Depth 12)
}

function Get-OllamaPs {
  return Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/ps' -TimeoutSec 5
}

function Save-OllamaPs([string]$Name) {
  $ps = Get-OllamaPs
  Write-Json (Join-Path $output $Name) $ps
  return $ps
}

function Model-IsLoaded($Ps,[string]$Model) {
  return @($Ps.models | Where-Object { $_.name -eq $Model }).Count -gt 0
}

function Invoke-DshTurn {
  param(
    [Parameter(Mandatory=$true)][string]$Name,
    [Parameter(Mandatory=$true)][string]$Patch,
    [Parameter(Mandatory=$true)][string]$Prompt,
    [string]$SessionId = ''
  )

  $turnDir = Join-Path (Join-Path $output 'turns') $Name
  New-Item -ItemType Directory -Path $turnDir -Force | Out-Null

  $stdinPath = Join-Path $turnDir 'stdin.txt'
  $stdoutPath = Join-Path $turnDir 'stdout.jsonl'
  $stderrPath = Join-Path $turnDir 'stderr.txt'
  Write-Utf8 $stdinPath $Prompt

  foreach ($value in @($dsh,$basePatch,$Patch,$SessionId)) {
    if ($value -and $value.Contains('"')) {
      throw 'DSH path, patch path, and session id values must not contain a double quote.'
    }
  }

  $resume = ''
  if ($SessionId) {
    $resume = ' --session-id "' + $SessionId + '"'
  }

  # Windows PowerShell 5.1 runs on .NET Framework, where
  # ProcessStartInfo.ArgumentList is unavailable. Use the same cmd.exe
  # launch path already proven by run-single-dsh.ps1.
  $nativeCommand = '"' + $dsh + '" --profile headless --patch "' + $basePatch +
    '" --patch "' + $Patch + '" --json' + $resume + ' -'

  $psi = [Diagnostics.ProcessStartInfo]::new()
  $psi.FileName = 'cmd.exe'
  $psi.Arguments = '/d /s /c "' + $nativeCommand + '"'
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardInput = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true

  $proc = [Diagnostics.Process]::new()
  $proc.StartInfo = $psi
  $started = Get-Date
  [void]$proc.Start()

  $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
  $stderrTask = $proc.StandardError.ReadToEndAsync()
  $proc.StandardInput.Write($Prompt)
  $proc.StandardInput.Close()

  $timedOut = -not $proc.WaitForExit($WallSecondsPerTurn * 1000)
  if ($timedOut) {
    try { & taskkill.exe /PID $proc.Id /T /F *> $null } catch {}
    try { $proc.WaitForExit() } catch {}
  }
  $stdout = $stdoutTask.GetAwaiter().GetResult()
  $stderr = $stderrTask.GetAwaiter().GetResult()
  $ended = Get-Date

  Write-Utf8 $stdoutPath $stdout
  Write-Utf8 $stderrPath $stderr

  $session = $null
  $final = ''
  $inputTokens = $null
  $outputTokens = $null
  $turnNumber = $null
  $turnEndKind = $null

  foreach ($line in ($stdout -split "\r?\n")) {
    if (-not $line.Trim()) { continue }
    try { $event = $line | ConvertFrom-Json } catch { continue }
    if ($event.type -eq 'session' -and $event.sessionId) { $session = [string]$event.sessionId }
    if ($event.type -eq 'final') { $final = [string]$event.text }
    if ($event.type -eq 'status' -and $event.phase -eq 'turn_start') { $turnNumber = $event.turn }
    if ($event.type -eq 'status' -and $event.phase -eq 'step_end' -and $event.usage) {
      $inputTokens = $event.usage.inputTokens
      $outputTokens = $event.usage.outputTokens
    }
    if ($event.type -eq 'status' -and $event.phase -eq 'turn_end' -and $event.reason) {
      $turnEndKind = $event.reason.kind
    }
  }

  $record = [ordered]@{
    name = $Name
    requestedSessionId = $(if ($SessionId) { $SessionId } else { $null })
    emittedSessionId = $session
    turn = $turnNumber
    final = $final
    inputTokens = $inputTokens
    outputTokens = $outputTokens
    wallSeconds = [math]::Round(($ended-$started).TotalSeconds,3)
    exitCode = $(if ($timedOut) { $null } else { $proc.ExitCode })
    timedOut = $timedOut
    turnEndKind = $turnEndKind
    stdin = $stdinPath
    stdout = $stdoutPath
    stderr = $stderrPath
  }
  Write-Json (Join-Path $turnDir 'turn.json') $record
  return [pscustomobject]$record
}

function Copy-SessionEvidence([string]$SessionId,[string]$Label) {
  if (-not (Test-Path -LiteralPath $sessionRoot)) { return $false }
  $dir = Get-ChildItem -LiteralPath $sessionRoot -Directory -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq $SessionId } | Select-Object -First 1
  if (-not $dir) { return $false }
  Copy-Item -LiteralPath $dir.FullName -Destination (Join-Path (Join-Path $output 'sessions') $Label) -Recurse
  return $true
}

function Exact([string]$Actual,[string]$Expected) {
  return [string]::Equals($Actual.Trim(),$Expected,[StringComparison]::Ordinal)
}

try {
  $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
  throw 'Ollama is not reachable at http://127.0.0.1:11434. Start Ollama before this test.'
}
$installed = @($tags.models.name)
foreach ($model in @($primaryModel,$alternateModel)) {
  if ($installed -notcontains $model) { throw "Required model is not installed: $model" }
}

$dump = (& $dsh --profile headless --dump-config 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the DSH headless profile.' }
if ($dump -notmatch '@zhangyi/dsh-llm-ollama') {
  throw 'Native Ollama plugin is not installed for DSH headless.'
}

Write-Host ''
Write-Host 'Session Persistence Test 01'
Write-Host "Primary model:   $primaryModel"
Write-Host "Alternate model: $alternateModel"
Write-Host "Output:          $output"
Write-Host ''

$turns = [ordered]@{}

$turns.A1 = Invoke-DshTurn -Name 'A1-create-worker' -Patch $primaryPatch -Prompt @'
You are WORKER_ALPHA for this session. Remember these session-local facts:
role=WORKER_ALPHA
marker=A_MARKER_7319
project=HARBOR
These facts belong only to this session. Reply exactly: A_READY
'@
$sessionA = $turns.A1.emittedSessionId
if (-not $sessionA) { throw 'Session A did not emit a session id.' }

$turns.B1 = Invoke-DshTurn -Name 'B1-create-reviewer' -Patch $primaryPatch -Prompt @'
You are REVIEWER_BETA for this session. Remember these session-local facts:
role=REVIEWER_BETA
marker=B_MARKER_2846
project=ORCHID
These facts belong only to this session. Reply exactly: B_READY
'@
$sessionB = $turns.B1.emittedSessionId
if (-not $sessionB) { throw 'Session B did not emit a session id.' }

$turns.A2 = Invoke-DshTurn -Name 'A2-recall-before-swap' -Patch $primaryPatch -SessionId $sessionA -Prompt @'
Without being told the values again, recall the role, marker, and project assigned in your first user message. Reply exactly in this format with the remembered values:
A_RECALL|<role>|<marker>|<project>
'@
$turns.B2 = Invoke-DshTurn -Name 'B2-recall-before-swap' -Patch $primaryPatch -SessionId $sessionB -Prompt @'
Without being told the values again, recall the role, marker, and project assigned in your first user message. Reply exactly in this format with the remembered values:
B_RECALL|<role>|<marker>|<project>
'@

$psBeforeStop = Save-OllamaPs 'ollama-ps-before-primary-stop.json'

$stopLog = Join-Path $output 'ollama-stop-primary.txt'
$stopPsi = [Diagnostics.ProcessStartInfo]::new()
$stopPsi.FileName = $ollama
$stopPsi.Arguments = 'stop "' + $primaryModel + '"'
$stopPsi.UseShellExecute = $false
$stopPsi.CreateNoWindow = $true
$stopPsi.RedirectStandardOutput = $true
$stopPsi.RedirectStandardError = $true
$stopProc = [Diagnostics.Process]::new()
$stopProc.StartInfo = $stopPsi
[void]$stopProc.Start()
$stopStdout = $stopProc.StandardOutput.ReadToEnd()
$stopStderr = $stopProc.StandardError.ReadToEnd()
$stopProc.WaitForExit()
Write-Utf8 $stopLog ($stopStdout + $stopStderr)
if ($stopProc.ExitCode -ne 0) {
  throw "ollama stop failed for $primaryModel with exit code $($stopProc.ExitCode). See $stopLog"
}

$deadline = (Get-Date).AddSeconds(30)
do {
  Start-Sleep -Milliseconds 500
  $psAfterStop = Get-OllamaPs
  $primaryStillLoaded = Model-IsLoaded $psAfterStop $primaryModel
} while ($primaryStillLoaded -and (Get-Date) -lt $deadline)
Write-Json (Join-Path $output 'ollama-ps-after-primary-stop.json') $psAfterStop

$turns.C1 = Invoke-DshTurn -Name 'C1-alternate-model' -Patch $alternatePatch -Prompt @'
You are SWAP_GAMMA. Remember marker=C_MARKER_9052 for this session. Reply exactly: C_READY
'@
$sessionC = $turns.C1.emittedSessionId
$psAfterAlternate = Save-OllamaPs 'ollama-ps-after-alternate.json'

$turns.A3 = Invoke-DshTurn -Name 'A3-recall-after-swap' -Patch $primaryPatch -SessionId $sessionA -Prompt @'
Without being told the values again, recall the role, marker, and project assigned in your first user message. Reply exactly in this format with the remembered values:
A_RECALL|<role>|<marker>|<project>
'@
$psAfterPrimaryReturn = Save-OllamaPs 'ollama-ps-after-primary-return.json'

$turns.B3 = Invoke-DshTurn -Name 'B3-recall-after-swap' -Patch $primaryPatch -SessionId $sessionB -Prompt @'
Without being told the values again, recall the role, marker, and project assigned in your first user message. Reply exactly in this format with the remembered values:
B_RECALL|<role>|<marker>|<project>
'@

$aOutputs = @($turns.A1.final,$turns.A2.final,$turns.A3.final) -join [Environment]::NewLine
$bOutputs = @($turns.B1.final,$turns.B2.final,$turns.B3.final) -join [Environment]::NewLine

$checks = [ordered]@{
  sessionIdsDistinct = ($sessionA -and $sessionB -and $sessionA -ne $sessionB)
  aInitialReady = Exact $turns.A1.final 'A_READY'
  bInitialReady = Exact $turns.B1.final 'B_READY'
  aRecallBeforeSwap = Exact $turns.A2.final 'A_RECALL|WORKER_ALPHA|A_MARKER_7319|HARBOR'
  bRecallBeforeSwap = Exact $turns.B2.final 'B_RECALL|REVIEWER_BETA|B_MARKER_2846|ORCHID'
  primaryUnloaded = (-not $primaryStillLoaded)
  alternateTurnReady = Exact $turns.C1.final 'C_READY'
  alternateLoaded = (Model-IsLoaded $psAfterAlternate $alternateModel)
  aRecallAfterSwap = Exact $turns.A3.final 'A_RECALL|WORKER_ALPHA|A_MARKER_7319|HARBOR'
  bRecallAfterSwap = Exact $turns.B3.final 'B_RECALL|REVIEWER_BETA|B_MARKER_2846|ORCHID'
  primaryReloaded = (Model-IsLoaded $psAfterPrimaryReturn $primaryModel)
  noBMarkerInA = ($aOutputs -notmatch [regex]::Escape('B_MARKER_2846'))
  noAMarkerInB = ($bOutputs -notmatch [regex]::Escape('A_MARKER_7319'))
}

$sessionEvidence = [ordered]@{
  A = Copy-SessionEvidence $sessionA 'session-a'
  B = Copy-SessionEvidence $sessionB 'session-b'
  C = $(if ($sessionC) { Copy-SessionEvidence $sessionC 'session-c' } else { $false })
}

$allPass = $true
foreach ($p in $checks.GetEnumerator()) {
  if (-not [bool]$p.Value) { $allPass = $false }
}

$result = [ordered]@{
  test = 'session-persistence-test-01'
  passed = $allPass
  primaryModel = $primaryModel
  alternateModel = $alternateModel
  sessionA = $sessionA
  sessionB = $sessionB
  sessionC = $sessionC
  checks = $checks
  sessionEvidenceCopied = $sessionEvidence
  turns = $turns
}
Write-Json (Join-Path $output 'result.json') $result

Write-Host ''
Write-Host 'Result:'
foreach ($p in $checks.GetEnumerator()) {
  Write-Host ("  {0}: {1}" -f $p.Key, $(if ($p.Value) { 'PASS' } else { 'FAIL' }))
}
Write-Host ''
Write-Host ("OVERALL: " + $(if ($allPass) { 'PASS' } else { 'FAIL' }))
Write-Host "Evidence: $(Join-Path $output 'result.json')"

if ($allPass) { exit 0 } else { exit 2 }
