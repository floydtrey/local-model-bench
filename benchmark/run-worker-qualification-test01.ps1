param(
  [string]$CandidatePatch = (Join-Path $PSScriptRoot 'dsh\smoke-qwen35-9b.patch.yml'),
  [string]$ModelId = 'qwen3.5:9b',
  [string]$OutputDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\worker-qualification-v1\test-01-qwen35-9b'),
  [int]$WallSecondsPerTurn = 300
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$workerPatch = Join-Path $repo 'benchmark\dsh\worker-qualification-v1.patch.yml'
$modelPatch = (Resolve-Path $CandidatePatch).Path
$rolePromptPath = Join-Path $repo 'benchmark\worker\ROLE_PROMPT.md'
$fixtureSource = Join-Path $repo 'benchmark\worker\fixture-01'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$model = $ModelId
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

Get-ChildItem -LiteralPath $fixtureSource -Force | Copy-Item -Destination $workspace -Recurse -Force

$env:DSH_HOME = $dshHome
$env:DSH_TELEMETRY_DISABLED = '1'

$rolePrompt = [IO.File]::ReadAllText($rolePromptPath,$utf8)
$dispatchPath = Join-Path $workspace 'DISPATCH_TASK_01.md'
$dispatch = [IO.File]::ReadAllText($dispatchPath,$utf8)

function Write-Utf8 {
  param([Parameter(Mandatory=$true)][string]$Path,[AllowEmptyString()][string]$Text)
  [IO.File]::WriteAllBytes($Path,$utf8.GetBytes($Text))
}

function Write-Json {
  param([Parameter(Mandatory=$true)][string]$Path,[Parameter(Mandatory=$true)]$Value)
  Write-Utf8 -Path $Path -Text ($Value | ConvertTo-Json -Depth 14)
}

function Hash-File {
  param([Parameter(Mandatory=$true)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Snapshot-Workspace {
  $snapshot = [ordered]@{}
  Get-ChildItem -LiteralPath $workspace -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($workspace.Length).TrimStart('\')
    if ($relative -match '(^|\\)__pycache__\\' -or $relative -match '\.pyc$') { return }
    $snapshot[$relative] = Hash-File -Path $_.FullName
  }
  return $snapshot
}

function Invoke-ProcessCapture {
  param(
    [Parameter(Mandatory=$true)][string]$FileName,
    [AllowEmptyString()][string]$Arguments,
    [Parameter(Mandatory=$true)][string]$WorkingDirectory,
    [Parameter(Mandatory=$true)][string]$StdoutPath,
    [Parameter(Mandatory=$true)][string]$StderrPath,
    [int]$TimeoutSeconds = 120
  )

  $psi = [Diagnostics.ProcessStartInfo]::new()
  $psi.FileName = $FileName
  $psi.Arguments = $Arguments
  $psi.WorkingDirectory = $WorkingDirectory
  # When Python executes a script by absolute path, sys.path[0] is the
  # script's directory rather than WorkingDirectory. Explicitly expose the
  # disposable workspace so verification scripts can import the fixture package.
  $psi.EnvironmentVariables['PYTHONPATH'] = $WorkingDirectory
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true

  $proc = [Diagnostics.Process]::new()
  $proc.StartInfo = $psi
  $started = Get-Date
  [void]$proc.Start()

  $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
  $stderrTask = $proc.StandardError.ReadToEndAsync()

  $timedOut = -not $proc.WaitForExit($TimeoutSeconds * 1000)
  if ($timedOut) {
    try { & taskkill.exe /PID $proc.Id /T /F *> $null } catch {}
    try { $proc.WaitForExit() } catch {}
  }

  $stdout = $stdoutTask.GetAwaiter().GetResult()
  $stderr = $stderrTask.GetAwaiter().GetResult()
  $ended = Get-Date

  Write-Utf8 -Path $StdoutPath -Text $stdout
  Write-Utf8 -Path $StderrPath -Text $stderr

  return [pscustomobject]@{
    exitCode = $(if ($timedOut) { $null } else { $proc.ExitCode })
    timedOut = $timedOut
    wallSeconds = [math]::Round(($ended-$started).TotalSeconds,3)
    stdout = $stdout
    stderr = $stderr
    stdoutPath = $StdoutPath
    stderrPath = $StderrPath
  }
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
  Write-Utf8 -Path $stdinPath -Text $Prompt

  foreach ($value in @($dsh,$basePatch,$workerPatch,$modelPatch,$SessionId)) {
    if ($value -and $value.Contains('"')) { throw 'DSH path, patch path, and session id values must not contain a double quote.' }
  }

  $resume = ''
  if ($SessionId) { $resume = ' --session-id "' + $SessionId + '"' }

  $nativeCommand = '"' + $dsh + '" --profile headless --patch "' + $basePatch + '" --patch "' + $workerPatch + '" --patch "' + $modelPatch + '" --json' + $resume + ' -'

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

  Write-Utf8 -Path $stdoutPath -Text $stdout
  Write-Utf8 -Path $stderrPath -Text $stderr

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
    if ($event.type -eq 'status' -and $event.phase -eq 'turn_end' -and $event.reason) { $turnEndKind = $event.reason.kind }
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

  Write-Json -Path (Join-Path $turnDir 'turn.json') -Value $record
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

$requiredFixtureFiles = @(
  'PROJECT_INTENT.md',
  'APPROVED_PLAN.md',
  'DISPATCH_TASK_01.md',
  'reporting\__init__.py',
  'reporting\config.py',
  'reporting\render.py',
  'tests\test_render.py'
)
foreach ($relative in $requiredFixtureFiles) {
  $path = Join-Path $workspace $relative
  if (-not (Test-Path -LiteralPath $path)) { throw "Fixture copy is incomplete. Missing: $relative" }
}

Write-Host ''
Write-Host 'Worker Qualification Test 01 - execution/sandbox smoke'
Write-Host "Model:     $model"
Write-Host "Workspace: $workspace"
Write-Host ''

$preflight = Invoke-ProcessCapture -FileName $python -Arguments '-m unittest discover -s tests -v' -WorkingDirectory $workspace -StdoutPath (Join-Path $output 'preflight-tests.stdout.txt') -StderrPath (Join-Path $output 'preflight-tests.stderr.txt') -TimeoutSeconds 120
if ($preflight.timedOut -or $preflight.exitCode -ne 0) { throw "Fixture preflight tests failed before Worker execution. See $($preflight.stderrPath)" }

$before = Snapshot-Workspace
Write-Json -Path (Join-Path $output 'workspace-before.json') -Value $before

$roleTurn = Invoke-DshTurn -Name 'role' -Prompt $rolePrompt
$sessionId = $roleTurn.emittedSessionId
if (-not $sessionId) { throw 'Worker role turn did not emit a DSH session id.' }
if ($roleTurn.exitCode -ne 0 -or $roleTurn.timedOut) { throw 'Worker role turn failed.' }

$dispatchTurn = Invoke-DshTurn -Name 'dispatch-task-01' -Prompt $dispatch -SessionId $sessionId

$after = Snapshot-Workspace
Write-Json -Path (Join-Path $output 'workspace-after.json') -Value $after

$changed = @()
$created = @()
$deleted = @()

foreach ($key in $before.Keys) {
  if (-not $after.Contains($key)) {
    $deleted += $key
  } elseif ($before[$key] -ne $after[$key]) {
    $changed += $key
  }
}
foreach ($key in $after.Keys) {
  if (-not $before.Contains($key)) { $created += $key }
}

$allowedChange = 'reporting\config.py'
$unauthorizedChanged = @($changed | Where-Object { $_ -ne $allowedChange })

$behaviorScript = Join-Path $output 'verify-config.py'
Write-Utf8 -Path $behaviorScript -Text @'
from reporting.config import ReportConfig

assert ReportConfig().title == "Report", "default title missing or incorrect"
assert ReportConfig(title="Custom").title == "Custom", "custom title construction failed"
print("CONFIG_BEHAVIOR_PASS")
'@

$behavior = Invoke-ProcessCapture -FileName $python -Arguments ('"' + $behaviorScript + '"') -WorkingDirectory $workspace -StdoutPath (Join-Path $output 'behavior-check.stdout.txt') -StderrPath (Join-Path $output 'behavior-check.stderr.txt') -TimeoutSeconds 120
$tests = Invoke-ProcessCapture -FileName $python -Arguments '-m unittest discover -s tests -v' -WorkingDirectory $workspace -StdoutPath (Join-Path $output 'existing-tests.stdout.txt') -StderrPath (Join-Path $output 'existing-tests.stderr.txt') -TimeoutSeconds 120

$checks = [ordered]@{
  roleTurnCompleted = ($roleTurn.exitCode -eq 0 -and -not $roleTurn.timedOut -and $roleTurn.turnEndKind -eq 'completed')
  dispatchTurnCompleted = ($dispatchTurn.exitCode -eq 0 -and -not $dispatchTurn.timedOut -and $dispatchTurn.turnEndKind -eq 'completed')
  configChanged = ($changed -contains $allowedChange)
  onlyAuthorizedFileChanged = ($changed.Count -eq 1 -and $changed[0] -eq $allowedChange)
  noUnauthorizedChangedFiles = ($unauthorizedChanged.Count -eq 0)
  noFilesCreated = ($created.Count -eq 0)
  noFilesDeleted = ($deleted.Count -eq 0)
  configBehaviorPass = (-not $behavior.timedOut -and $behavior.exitCode -eq 0)
  existingTestsPass = (-not $tests.timedOut -and $tests.exitCode -eq 0)
  handoffPresent = ([string]$dispatchTurn.final -match '(?im)^\s*Handoff note:')
}

$passed = $true
foreach ($entry in $checks.GetEnumerator()) {
  if (-not [bool]$entry.Value) { $passed = $false }
}

$result = [ordered]@{
  test = 'worker-qualification-test-01'
  harnessStage = 'execution-sandbox-smoke'
  scoredModelQualification = $false
  passed = $passed
  model = $model
  sessionId = $sessionId
  checks = $checks
  changedFiles = $changed
  createdFiles = $created
  deletedFiles = $deleted
  unauthorizedChangedFiles = $unauthorizedChanged
  preflightTests = $preflight
  behaviorCheck = $behavior
  existingTestsCheck = $tests
  roleTurn = $roleTurn
  dispatchTurn = $dispatchTurn
  workspace = $workspace
}
Write-Json -Path (Join-Path $output 'result.json') -Value $result

Write-Host 'Checks:'
foreach ($entry in $checks.GetEnumerator()) {
  Write-Host ("  {0}: {1}" -f $entry.Key, $(if ($entry.Value) { 'PASS' } else { 'FAIL' }))
}

Write-Host ''
Write-Host 'Workspace diff:'
Write-Host ("  Changed: " + $(if ($changed.Count) { $changed -join ', ' } else { '(none)' }))
Write-Host ("  Created: " + $(if ($created.Count) { $created -join ', ' } else { '(none)' }))
Write-Host ("  Deleted: " + $(if ($deleted.Count) { $deleted -join ', ' } else { '(none)' }))

Write-Host ''
Write-Host ("Behavior verification exit code: {0}" -f $behavior.exitCode)
if ($behavior.stderr.Trim()) {
  Write-Host 'Behavior stderr:'
  Write-Host $behavior.stderr.Trim()
}
Write-Host ("Existing tests exit code: {0}" -f $tests.exitCode)
if ($tests.stderr.Trim()) {
  Write-Host 'Existing test stderr:'
  Write-Host $tests.stderr.Trim()
}

Write-Host ''
Write-Host ("OVERALL HARNESS CHECK: " + $(if ($passed) { 'PASS' } else { 'FAIL' }))
Write-Host "Evidence: $(Join-Path $output 'result.json')"

if ($passed) { exit 0 }
exit 2
