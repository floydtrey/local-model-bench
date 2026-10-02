param(
  [string]$OutputDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\session-persistence-v1\test-02'),
  [int]$WallSecondsPerTurn = 180
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$modelPatch = Join-Path $repo 'benchmark\dsh\smoke-qwen35-9b.patch.yml'
$fixturePath = Join-Path $repo 'benchmark\session-persistence\context-fixture-02.md'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$model = 'qwen3.5:9b'
$utf8 = [Text.UTF8Encoding]::new($false)

foreach ($required in @($dsh,$basePatch,$modelPatch,$fixturePath)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required path: $required" }
}
if ($WallSecondsPerTurn -lt 10) { throw 'WallSecondsPerTurn must be at least 10.' }

$output = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) { throw "Output directory already exists: $output" }
New-Item -ItemType Directory -Path $output -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $output 'turns') -Force | Out-Null

$env:DSH_HOME = $dshHome
$env:DSH_TELEMETRY_DISABLED = '1'
$fixture = [IO.File]::ReadAllText($fixturePath,$utf8)

function Write-Utf8([string]$Path,[string]$Text) {
  [IO.File]::WriteAllBytes($Path,$utf8.GetBytes($Text))
}
function Write-Json([string]$Path,$Value) {
  Write-Utf8 $Path ($Value | ConvertTo-Json -Depth 14)
}
function Exact([string]$Actual,[string]$Expected) {
  return [string]::Equals($Actual.Trim(),$Expected,[StringComparison]::Ordinal)
}
function Sum-Field($Turns,[string[]]$Names,[string]$Field) {
  $sum = 0
  foreach ($name in $Names) {
    $v = $Turns[$name].$Field
    if ($null -ne $v) { $sum += [int64]$v }
  }
  return $sum
}
function Sum-Wall($Turns,[string[]]$Names) {
  $sum = 0.0
  foreach ($name in $Names) { $sum += [double]$Turns[$name].wallSeconds }
  return [math]::Round($sum,3)
}

function Invoke-DshTurn {
  param(
    [Parameter(Mandatory=$true)][string]$Name,
    [Parameter(Mandatory=$true)][string]$Prompt,
    [string]$SessionId = ''
  )

  $turnDir = Join-Path (Join-Path $output 'turns') $Name
  New-Item -ItemType Directory -Path $turnDir -Force | Out-Null
  $stdinPath = Join-Path $turnDir 'stdin.txt'
  $stdoutPath = Join-Path $turnDir 'stdout.jsonl'
  $stderrPath = Join-Path $turnDir 'stderr.txt'
  Write-Utf8 $stdinPath $Prompt

  foreach ($value in @($dsh,$basePatch,$modelPatch,$SessionId)) {
    if ($value -and $value.Contains('"')) { throw 'DSH path, patch path, and session id values must not contain a double quote.' }
  }

  $resume = ''
  if ($SessionId) { $resume = ' --session-id "' + $SessionId + '"' }
  $nativeCommand = '"' + $dsh + '" --profile headless --patch "' + $basePatch +
    '" --patch "' + $modelPatch + '" --json' + $resume + ' -'

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
  $turn = $null
  $turnEndKind = $null

  foreach ($line in ($stdout -split "\r?\n")) {
    if (-not $line.Trim()) { continue }
    try { $event = $line | ConvertFrom-Json } catch { continue }
    if ($event.type -eq 'session' -and $event.sessionId) { $session = [string]$event.sessionId }
    if ($event.type -eq 'final') { $final = [string]$event.text }
    if ($event.type -eq 'status' -and $event.phase -eq 'turn_start') { $turn = $event.turn }
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
    turn = $turn
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

try {
  $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
  throw 'Ollama is not reachable at http://127.0.0.1:11434. Start Ollama before this test.'
}
if (@($tags.models.name) -notcontains $model) { throw "Required model is not installed: $model" }

$dump = (& $dsh --profile headless --dump-config 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the DSH headless profile.' }
if ($dump -notmatch '@zhangyi/dsh-llm-ollama') { throw 'Native Ollama plugin is not installed for DSH headless.' }

Write-Host ''
Write-Host 'Session Context Test 02'
Write-Host "Model:  $model"
Write-Host "Output: $output"
Write-Host ''

$turns = [ordered]@{}

# Architecture A: two persistent role sessions.
$turns.A1 = Invoke-DshTurn -Name 'A1-worker-create' -Prompt @"
You are WORKER_PRIMARY. Your private role marker is W_MARKER_4471.
Your project is AURORA-LEDGER.
Remain the Worker for this entire session. A Reviewer will operate in a different session.
Read and retain this project context:

$fixture

Reply exactly: A_WORKER_READY
"@
$workerA = $turns.A1.emittedSessionId
if (-not $workerA) { throw 'Architecture A Worker did not emit a session id.' }

$turns.A2 = Invoke-DshTurn -Name 'A2-worker-checkpoint1' -SessionId $workerA -Prompt @'
Complete checkpoint 1 without changing roles. The synthetic artifact is ARTIFACT_ONE_OK. Reply exactly: A_WORK_1
'@

$turns.R1 = Invoke-DshTurn -Name 'R1-reviewer-create' -Prompt @"
You are REVIEWER_PRIMARY. Your private role marker is R_MARKER_5512.
Your project is AURORA-LEDGER.
Remain the Reviewer for this entire session.
Read and retain this same project context:

$fixture

Review artifact 1: ARTIFACT_ONE_OK.
For this synthetic comparison, the artifact passes. Reply exactly: A_REVIEW_1_PASS
"@
$reviewerA = $turns.R1.emittedSessionId
if (-not $reviewerA) { throw 'Architecture A Reviewer did not emit a session id.' }

$turns.A3 = Invoke-DshTurn -Name 'A3-worker-return1' -SessionId $workerA -Prompt @'
Review outcome 1: PASS. Resume your existing session role. Without being told your original role marker again, reply exactly:
A_RETURN_1|<role>|<marker>|<project>
using the values from your first message.
'@

$turns.A4 = Invoke-DshTurn -Name 'A4-worker-checkpoint2' -SessionId $workerA -Prompt @'
Complete checkpoint 2 without changing roles. The synthetic artifact is ARTIFACT_TWO_OK. Reply exactly: A_WORK_2
'@

$turns.R2 = Invoke-DshTurn -Name 'R2-reviewer-resume' -SessionId $reviewerA -Prompt @'
Review artifact 2: ARTIFACT_TWO_OK. Use the project context already in this Reviewer session. For this synthetic comparison, the artifact passes. Reply exactly: A_REVIEW_2_PASS
'@

$turns.A5 = Invoke-DshTurn -Name 'A5-worker-return2' -SessionId $workerA -Prompt @'
Review outcome 2: PASS. Resume your existing session role. Without being told your original role marker again, reply exactly:
A_RETURN_2|<role>|<marker>|<project>
using the values from your first message.
'@

# Architecture B: one session repeatedly switched between roles.
$turns.S1 = Invoke-DshTurn -Name 'S1-single-worker-create' -Prompt @"
You are WORKER_PRIMARY. Your private role marker is W_MARKER_4471.
Your project is AURORA-LEDGER.
Read and retain this project context:

$fixture

Reply exactly: S_WORKER_READY
"@
$single = $turns.S1.emittedSessionId
if (-not $single) { throw 'Architecture B session did not emit a session id.' }

$turns.S2 = Invoke-DshTurn -Name 'S2-single-worker-checkpoint1' -SessionId $single -Prompt @'
Complete checkpoint 1 as WORKER_PRIMARY. The synthetic artifact is ARTIFACT_ONE_OK. Reply exactly: S_WORK_1
'@

$turns.S3 = Invoke-DshTurn -Name 'S3-single-switch-reviewer1' -SessionId $single -Prompt @'
Temporarily change role to REVIEWER_TEMP for this review only. Reviewer-only marker=S_REVIEWER_MARKER_8821.
Review artifact 1: ARTIFACT_ONE_OK using the project context already in this session.
For this synthetic comparison, the artifact passes. Reply exactly: S_REVIEW_1_PASS
'@

$turns.S4 = Invoke-DshTurn -Name 'S4-single-return-worker1' -SessionId $single -Prompt @'
The temporary review role is finished. Return to the original role from the first message. Without being told the original role marker again, reply exactly:
S_RETURN_1|<role>|<marker>|<project>
using the original Worker values.
'@

$turns.S5 = Invoke-DshTurn -Name 'S5-single-worker-checkpoint2' -SessionId $single -Prompt @'
Complete checkpoint 2 in your restored original Worker role. The synthetic artifact is ARTIFACT_TWO_OK. Reply exactly: S_WORK_2
'@

$turns.S6 = Invoke-DshTurn -Name 'S6-single-switch-reviewer2' -SessionId $single -Prompt @'
Temporarily change role to REVIEWER_TEMP again for this review only. Reviewer-only marker=S_REVIEWER_MARKER_8821.
Review artifact 2: ARTIFACT_TWO_OK using the project context already in this session.
For this synthetic comparison, the artifact passes. Reply exactly: S_REVIEW_2_PASS
'@

$turns.S7 = Invoke-DshTurn -Name 'S7-single-return-worker2' -SessionId $single -Prompt @'
The temporary review role is finished. Return to the original role from the first message. Without being told the original role marker again, reply exactly:
S_RETURN_2|<role>|<marker>|<project>
using the original Worker values.
'@

$aNames = @('A1','A2','R1','A3','A4','R2','A5')
$bNames = @('S1','S2','S3','S4','S5','S6','S7')
$aWorkerNames = @('A1','A2','A3','A4','A5')
$aReviewerNames = @('R1','R2')
$bWorkerNames = @('S1','S2','S4','S5','S7')
$bReviewerNames = @('S3','S6')

$checks = [ordered]@{
  architectureAHasDistinctRoleSessions = ($workerA -and $reviewerA -and $workerA -ne $reviewerA)
  aWorkerReturn1 = Exact $turns.A3.final 'A_RETURN_1|WORKER_PRIMARY|W_MARKER_4471|AURORA-LEDGER'
  aWorkerReturn2 = Exact $turns.A5.final 'A_RETURN_2|WORKER_PRIMARY|W_MARKER_4471|AURORA-LEDGER'
  aReviewerTurn1 = Exact $turns.R1.final 'A_REVIEW_1_PASS'
  aReviewerTurn2 = Exact $turns.R2.final 'A_REVIEW_2_PASS'
  bWorkerReturn1 = Exact $turns.S4.final 'S_RETURN_1|WORKER_PRIMARY|W_MARKER_4471|AURORA-LEDGER'
  bWorkerReturn2 = Exact $turns.S7.final 'S_RETURN_2|WORKER_PRIMARY|W_MARKER_4471|AURORA-LEDGER'
  bReviewerTurn1 = Exact $turns.S3.final 'S_REVIEW_1_PASS'
  bReviewerTurn2 = Exact $turns.S6.final 'S_REVIEW_2_PASS'
  noReviewerMarkerInAWorkerReturns = (([string]$turns.A3.final + [string]$turns.A5.final) -notmatch 'R_MARKER_5512')
  noReviewerMarkerInBWorkerReturns = (([string]$turns.S4.final + [string]$turns.S7.final) -notmatch 'S_REVIEWER_MARKER_8821')
}

$allTurnsCompleted = $true
foreach ($name in ($aNames + $bNames)) {
  $t = $turns[$name]
  if ($t.exitCode -ne 0 -or $t.timedOut -or $t.turnEndKind -ne 'completed' -or $null -eq $t.inputTokens) {
    $allTurnsCompleted = $false
  }
}
$checks.allTurnsCompletedWithUsage = $allTurnsCompleted

$metrics = [ordered]@{
  architectureA = [ordered]@{
    workerSessionId = $workerA
    reviewerSessionId = $reviewerA
    return1InputTokens = $turns.A3.inputTokens
    return2InputTokens = $turns.A5.inputTokens
    workerInputTokens = Sum-Field $turns $aWorkerNames 'inputTokens'
    reviewerInputTokens = Sum-Field $turns $aReviewerNames 'inputTokens'
    totalInputTokens = Sum-Field $turns $aNames 'inputTokens'
    totalOutputTokens = Sum-Field $turns $aNames 'outputTokens'
    totalWallSeconds = Sum-Wall $turns $aNames
  }
  architectureB = [ordered]@{
    sessionId = $single
    return1InputTokens = $turns.S4.inputTokens
    return2InputTokens = $turns.S7.inputTokens
    workerPhaseInputTokens = Sum-Field $turns $bWorkerNames 'inputTokens'
    reviewerPhaseInputTokens = Sum-Field $turns $bReviewerNames 'inputTokens'
    totalInputTokens = Sum-Field $turns $bNames 'inputTokens'
    totalOutputTokens = Sum-Field $turns $bNames 'outputTokens'
    totalWallSeconds = Sum-Wall $turns $bNames
  }
}
$metrics.comparison = [ordered]@{
  return1InputTokenDeltaSingleMinusTwoSession = ([int64]$turns.S4.inputTokens - [int64]$turns.A3.inputTokens)
  return2InputTokenDeltaSingleMinusTwoSession = ([int64]$turns.S7.inputTokens - [int64]$turns.A5.inputTokens)
  totalInputTokenDeltaSingleMinusTwoSession = ([int64]$metrics.architectureB.totalInputTokens - [int64]$metrics.architectureA.totalInputTokens)
  totalWallDeltaSingleMinusTwoSession = [math]::Round(([double]$metrics.architectureB.totalWallSeconds - [double]$metrics.architectureA.totalWallSeconds),3)
}

$passed = $true
foreach ($p in $checks.GetEnumerator()) {
  if (-not [bool]$p.Value) { $passed = $false }
}

$result = [ordered]@{
  test = 'session-context-test-02'
  passed = $passed
  model = $model
  checks = $checks
  metrics = $metrics
  turns = $turns
}
Write-Json (Join-Path $output 'result.json') $result

Write-Host 'Correctness checks:'
foreach ($p in $checks.GetEnumerator()) {
  Write-Host ("  {0}: {1}" -f $p.Key, $(if ($p.Value) { 'PASS' } else { 'FAIL' }))
}
Write-Host ''
Write-Host 'Context measurements:'
Write-Host ("  Two-session Worker return 1 input: {0}" -f $metrics.architectureA.return1InputTokens)
Write-Host ("  Single-session Worker return 1 input: {0}" -f $metrics.architectureB.return1InputTokens)
Write-Host ("  Delta (single - two): {0}" -f $metrics.comparison.return1InputTokenDeltaSingleMinusTwoSession)
Write-Host ("  Two-session Worker return 2 input: {0}" -f $metrics.architectureA.return2InputTokens)
Write-Host ("  Single-session Worker return 2 input: {0}" -f $metrics.architectureB.return2InputTokens)
Write-Host ("  Delta (single - two): {0}" -f $metrics.comparison.return2InputTokenDeltaSingleMinusTwoSession)
Write-Host ("  Two-session total input tokens: {0}" -f $metrics.architectureA.totalInputTokens)
Write-Host ("  Single-session total input tokens: {0}" -f $metrics.architectureB.totalInputTokens)
Write-Host ("  Total delta (single - two): {0}" -f $metrics.comparison.totalInputTokenDeltaSingleMinusTwoSession)
Write-Host ''
Write-Host ("OVERALL CORRECTNESS: " + $(if ($passed) { 'PASS' } else { 'FAIL' }))
Write-Host "Evidence: $(Join-Path $output 'result.json')"

if ($passed) { exit 0 } else { exit 2 }
