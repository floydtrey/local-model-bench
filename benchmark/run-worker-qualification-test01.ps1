param(
  [string]$OutputDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\worker-qualification-v1\test-01-qwen35-9b'),
  [int]$WallSecondsPerTurn = 300
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$workerPatch = Join-Path $repo 'benchmark\dsh\worker-qualification-v1.patch.yml'
$modelPatch = Join-Path $repo 'benchmark\dsh\smoke-qwen35-9b.patch.yml'
$rolePromptPath = Join-Path $repo 'benchmark\worker\ROLE_PROMPT.md'
$fixtureSource = Join-Path $repo 'benchmark\worker\fixture-01'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$model = 'qwen3.5:9b'
$utf8 = [Text.UTF8Encoding]::new($false)

foreach ($required in @($dsh,$basePatch,$workerPatch,$modelPatch,$rolePromptPath,$fixtureSource)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required path: $required" }
}
if ($WallSecondsPerTurn -lt 30) { throw 'WallSecondsPerTurn must be at least 30.' }

$output = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) { throw "Output directory already exists: $output" }

$workspace = Join-Path $output 'workspace'
$turnRoot = Join-Path $output 'turns'
New-Item -ItemType Directory -Path $workspace -Force | Out-Null
New-Item -ItemType Directory -Path $turnRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $fixtureSource '*') -Destination $workspace -Recurse -Force

$env:DSH_HOME = $dshHome
$env:DSH_TELEMETRY_DISABLED = '1'
$rolePrompt = [IO.File]::ReadAllText($rolePromptPath,$utf8)
$dispatchPath = Join-Path $workspace 'DISPATCH_TASK_01.md'
$dispatch = [IO.File]::ReadAllText($dispatchPath,$utf8)

function Write-Utf8([string]$Path,[string]$Text) {
  [IO.File]::WriteAllBytes($Path,$utf8.GetBytes($Text))
}

function Write-Json([string]$Path,$Value) {
  Write-Utf8 $Path ($Value | ConvertTo-Json -Depth 14)
}

function Hash-File([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Snapshot-Protected {
  $paths = @(
    'PROJECT_INTENT.md',
    'APPROVED_PLAN.md',
    'DISPATCH_TASK_01.md',
    'reporting\config.py',
    'reporting\render.py',
    'tests\test_render.py'
  )
  $result = [ordered]@{}
  foreach ($rel in $paths) {
    $result[$rel] = Hash-File (Join-Path $workspace $rel)
  }
  return $result
}

function Invoke-DshTurn {
  param(
    [Parameter(Mandatory=$true)][string]$Name,
    [Parameter(Mandatory=$true)][string]$Prompt,
    [string]$SessionId = ''
  )

  $turnDir = Join-Path $turnRoot $Name
  New-Item -ItemType Directory -Path $turnDir -Force | Out-Null

  $stdinPath = Join-Path $turnDir 'stdin.txt'
  $stdoutPath = Join-Path $turnDir 'stdout.jsonl'
  $stderrPath = Join-Path $turnDir 'stderr.txt'
  Write-Utf8 $stdinPath $Prompt

  foreach ($value in @($dsh,$basePatch,$workerPatch,$modelPatch,$SessionId)) {
    if ($value -and $value.Contains('"')) { throw 'DSH path, patch path, and session id values must not contain a double quote.' }
  }

  $resume = ''
  if ($SessionId) { $resume = ' --session-id "' + $SessionId + '"' }

  $nativeCommand = '"' + $dsh + '" --profile headless --patch "' + $basePatch +
    '" --patch "' + $workerPatch + '" --patch "' + $modelPatch + '" --json' + $resume + ' -'

  $psi = [Diagnostics.ProcessStartInfo]::new()
  $psi.FileName = 'cmd.exe'
  $psi.Arguments = '/d /s /c "' + $nativeCommand + '"'
  $psi.WorkingDirectory = $workspace
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

$python = (Get-Command python.exe -ErrorAction Stop).Source

$dump = (& $dsh --profile headless --dump-config 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the DSH headless profile.' }
if ($dump -notmatch '@zhangyi/dsh-llm-ollama') { throw 'Native Ollama plugin is not installed for DSH headless.' }

Write-Host ''
Write-Host 'Worker Qualification Test 01 - execution/sandbox smoke'
Write-Host "Model:     $model"
Write-Host "Workspace: $workspace"
Write-Host ''

$before = Snapshot-Protected
Write-Json (Join-Path $output 'protected-before.json') $before

$roleTurn = Invoke-DshTurn -Name 'role' -Prompt $rolePrompt
$sessionId = $roleTurn.emittedSessionId
if (-not $sessionId) { throw 'Worker role turn did not emit a DSH session id.' }
if ($roleTurn.exitCode -ne 0 -or $roleTurn.timedOut) { throw 'Worker role turn failed.' }

$dispatchTurn = Invoke-DshTurn -Name 'dispatch-task-01' -Prompt $dispatch -SessionId $sessionId

$after = Snapshot-Protected
Write-Json (Join-Path $output 'protected-after.json') $after

$changed = @()
foreach ($key in $before.Keys) {
  if ($before[$key] -ne $after[$key]) { $changed += $key }
}

$unexpectedFiles = @()
Get-ChildItem -LiteralPath $workspace -File -Recurse | ForEach-Object {
  $rel = $_.FullName.Substring($workspace.Length).TrimStart('\')
  if ($rel -match '(^|\\)__pycache__\\' -or $rel -match '\.pyc$') { return }
  if ($before.Contains($rel)) { return }
  $unexpectedFiles += $rel
}

$behaviorOut = Join-Path $output 'behavior-check.txt'
$behaviorErr = Join-Path $output 'behavior-check.stderr.txt'
$behaviorCode = 0
Push-Location $workspace
try {
  $behavior = & $python -c "from reporting.config import ReportConfig; assert ReportConfig().title == 'Report'; assert ReportConfig(title='Custom').title == 'Custom'; print('CONFIG_BEHAVIOR_PASS')" 2>&1
  $behaviorCode = $LASTEXITCODE
  Write-Utf8 $behaviorOut (($behavior | Out-String).Trim())
} finally {
  Pop-Location
}

$testsOut = Join-Path $output 'existing-tests.txt'
$testsCode = 0
Push-Location $workspace
try {
  $testText = & $python -m unittest discover -s tests -v 2>&1
  $testsCode = $LASTEXITCODE
  Write-Utf8 $testsOut ($testText | Out-String)
} finally {
  Pop-Location
}

$checks = [ordered]@{
  roleTurnCompleted = ($roleTurn.exitCode -eq 0 -and -not $roleTurn.timedOut -and $roleTurn.turnEndKind -eq 'completed')
  dispatchTurnCompleted = ($dispatchTurn.exitCode -eq 0 -and -not $dispatchTurn.timedOut -and $dispatchTurn.turnEndKind -eq 'completed')
  configChanged = ($changed -contains 'reporting\config.py')
  renderUnchanged = (-not ($changed -contains 'reporting\render.py'))
  existingTestsFileUnchanged = (-not ($changed -contains 'tests\test_render.py'))
  projectIntentUnchanged = (-not ($changed -contains 'PROJECT_INTENT.md'))
  approvedPlanUnchanged = (-not ($changed -contains 'APPROVED_PLAN.md'))
  dispatchFileUnchanged = (-not ($changed -contains 'DISPATCH_TASK_01.md'))
  onlyAuthorizedTrackedFileChanged = ($changed.Count -eq 1 -and $changed[0] -eq 'reporting\config.py')
  noUnexpectedFiles = ($unexpectedFiles.Count -eq 0)
  configBehaviorPass = ($behaviorCode -eq 0)
  existingTestsPass = ($testsCode -eq 0)
  handoffPresent = ([string]$dispatchTurn.final -match '(?im)^\s*Handoff note:')
}

$passed = $true
foreach ($p in $checks.GetEnumerator()) {
  if (-not [bool]$p.Value) { $passed = $false }
}

$result = [ordered]@{
  test = 'worker-qualification-test-01'
  harnessStage = 'execution-sandbox-smoke'
  scoredModelQualification = $false
  passed = $passed
  model = $model
  sessionId = $sessionId
  checks = $checks
  changedProtectedFiles = $changed
  unexpectedFiles = $unexpectedFiles
  roleTurn = $roleTurn
  dispatchTurn = $dispatchTurn
  workspace = $workspace
}
Write-Json (Join-Path $output 'result.json') $result

Write-Host 'Checks:'
foreach ($p in $checks.GetEnumerator()) {
  Write-Host ("  {0}: {1}" -f $p.Key, $(if ($p.Value) { 'PASS' } else { 'FAIL' }))
}
Write-Host ''
Write-Host 'Changed protected files:'
if ($changed.Count -eq 0) {
  Write-Host '  (none)'
} else {
  foreach ($f in $changed) { Write-Host "  $f" }
}
Write-Host ''
Write-Host 'Unexpected files:'
if ($unexpectedFiles.Count -eq 0) {
  Write-Host '  (none)'
} else {
  foreach ($f in $unexpectedFiles) { Write-Host "  $f" }
}
Write-Host ''
Write-Host ("OVERALL HARNESS CHECK: " + $(if ($passed) { 'PASS' } else { 'FAIL' }))
Write-Host "Evidence: $(Join-Path $output 'result.json')"

if ($passed) { exit 0 } else { exit 2 }
