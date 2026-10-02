param(
  [Parameter(Mandatory=$true)][string]$CandidatePatch,
  [Parameter(Mandatory=$true)][string]$ModelId,
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [int]$WallSecondsPerTurn = 300
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$workerPatch = Join-Path $repo 'benchmark\dsh\worker-qualification-v1.patch.yml'
$modelPatch = (Resolve-Path $CandidatePatch).Path
$rolePromptPath = Join-Path $repo 'benchmark\worker\ROLE_PROMPT.md'
$fixtureSource = Join-Path $repo 'benchmark\worker\fixture-02'
$intentPath = Join-Path $repo 'benchmark\planner\intent-04-batch-export.md'
$planPath = Join-Path $repo 'benchmark\governor\plans\plan-b-medium.md'
$verifierPath = Join-Path $repo 'benchmark\worker\intent04\verify_stage.py'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$utf8 = [Text.UTF8Encoding]::new($false)

$tasks = @(
  [pscustomobject]@{
    id = 1
    name = 'register-export-csv'
    spec = (Join-Path $repo 'benchmark\worker\intent04\TASK_01.md')
    allowed = 'inventory\cli.py'
  },
  [pscustomobject]@{
    id = 2
    name = 'csv-retrieval-formatting'
    spec = (Join-Path $repo 'benchmark\worker\intent04\TASK_02.md')
    allowed = 'inventory\cli.py'
  },
  [pscustomobject]@{
    id = 3
    name = 'file-output-errors'
    spec = (Join-Path $repo 'benchmark\worker\intent04\TASK_03.md')
    allowed = 'inventory\cli.py'
  },
  [pscustomobject]@{
    id = 4
    name = 'regression-tests'
    spec = (Join-Path $repo 'benchmark\worker\intent04\TASK_04.md')
    allowed = 'tests\test_cli.py'
  }
)

$required = @(
  $dsh,$basePatch,$workerPatch,$modelPatch,$rolePromptPath,$fixtureSource,
  $intentPath,$planPath,$verifierPath
)
$required += @($tasks | ForEach-Object { $_.spec })

foreach ($path in $required) {
  if (-not (Test-Path -LiteralPath $path)) { throw "Missing required path: $path" }
}
if ($WallSecondsPerTurn -lt 30) { throw 'WallSecondsPerTurn must be at least 30.' }

$output = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) { throw "Output directory already exists: $output" }

$workspace = Join-Path $output 'workspace'
$turnRoot = Join-Path $output 'turns'
$taskRoot = Join-Path $output 'tasks'
New-Item -ItemType Directory -Path $workspace -Force | Out-Null
New-Item -ItemType Directory -Path $turnRoot -Force | Out-Null
New-Item -ItemType Directory -Path $taskRoot -Force | Out-Null

Get-ChildItem -LiteralPath $fixtureSource -Force | Copy-Item -Destination $workspace -Recurse -Force

$intentText = [IO.File]::ReadAllText($intentPath,$utf8)
$planText = [IO.File]::ReadAllText($planPath,$utf8)
$rolePrompt = [IO.File]::ReadAllText($rolePromptPath,$utf8)
[IO.File]::WriteAllText((Join-Path $workspace 'PROJECT_INTENT.md'),$intentText,$utf8)
[IO.File]::WriteAllText((Join-Path $workspace 'APPROVED_PLAN.md'),$planText,$utf8)

$env:DSH_HOME = $dshHome
$env:DSH_TELEMETRY_DISABLED = '1'

function Write-Utf8 {
  param([Parameter(Mandatory=$true)][string]$Path,[AllowEmptyString()][string]$Text)
  [IO.File]::WriteAllBytes($Path,$utf8.GetBytes($Text))
}

function Write-Json {
  param([Parameter(Mandatory=$true)][string]$Path,[Parameter(Mandatory=$true)]$Value)
  Write-Utf8 -Path $Path -Text ($Value | ConvertTo-Json -Depth 20)
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

function Compare-Snapshots {
  param($Before,$After)
  $changed = @()
  $created = @()
  $deleted = @()
  foreach ($key in $Before.Keys) {
    if (-not $After.Contains($key)) {
      $deleted += $key
    } elseif ($Before[$key] -ne $After[$key]) {
      $changed += $key
    }
  }
  foreach ($key in $After.Keys) {
    if (-not $Before.Contains($key)) { $created += $key }
  }
  return [pscustomobject]@{
    changed = @($changed)
    created = @($created)
    deleted = @($deleted)
  }
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
    [string]$SessionId = '',
    [switch]$EnableWorkerTools
  )

  $turnDir = Join-Path $turnRoot $Name
  New-Item -ItemType Directory -Path $turnDir -Force | Out-Null
  $stdinPath = Join-Path $turnDir 'stdin.txt'
  $stdoutPath = Join-Path $turnDir 'stdout.jsonl'
  $stderrPath = Join-Path $turnDir 'stderr.txt'
  Write-Utf8 -Path $stdinPath -Text $Prompt

  foreach ($value in @($dsh,$basePatch,$workerPatch,$modelPatch,$SessionId)) {
    if ($value -and $value.Contains('"')) {
      throw 'DSH path, patch path, and session id values must not contain a double quote.'
    }
  }

  $resume = ''
  if ($SessionId) { $resume = ' --session-id "' + $SessionId + '"' }

  $patchArgs = ' --patch "' + $basePatch + '"'
  if ($EnableWorkerTools) { $patchArgs += ' --patch "' + $workerPatch + '"' }
  $patchArgs += ' --patch "' + $modelPatch + '"'
  $nativeCommand = '"' + $dsh + '" --profile headless' + $patchArgs + ' --json' + $resume + ' -'

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
  Write-Json -Path (Join-Path $turnDir 'turn.json') -Value $record
  return [pscustomobject]$record
}

function Get-Handoff {
  param([AllowEmptyString()][string]$FinalText)
  $match = [regex]::Match($FinalText,'(?ims)^\s*Handoff note:\s*(.*)$')
  if (-not $match.Success) { return $null }
  return ('Handoff note: ' + $match.Groups[1].Value.Trim())
}

try {
  $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
  throw 'Ollama is not reachable at http://127.0.0.1:11434.'
}
if (@($tags.models.name) -notcontains $ModelId) { throw "Required model is not installed: $ModelId" }

$python = (Get-Command python.exe -ErrorAction Stop).Source
$dshVersion = (& $dsh --version 2>&1 | Out-String).Trim()
if ($dshVersion -ne '0.1.6-alpha.2') {
  throw "Intent 04 Worker qualification requires DSH 0.1.6-alpha.2; found '$dshVersion'."
}

$pluginRoot = Join-Path $dshHome 'profiles\headless\node_modules\@zhangyi\dsh-llm-ollama'
$pluginPackagePath = Join-Path $pluginRoot 'package.json'
$pluginIndexPath = Join-Path $pluginRoot 'lib\index.js'
foreach ($path in @($pluginPackagePath,$pluginIndexPath)) {
  if (-not (Test-Path -LiteralPath $path)) { throw "Missing runtime-qualified plugin path: $path" }
}
$pluginPackage = Get-Content -LiteralPath $pluginPackagePath -Raw | ConvertFrom-Json
if ([string]$pluginPackage.version -ne '0.1.17') {
  throw "Intent 04 Worker qualification requires dsh-llm-ollama 0.1.17; found '$($pluginPackage.version)'."
}
$pluginSource = [IO.File]::ReadAllText($pluginIndexPath,$utf8)
if (-not $pluginSource.Contains("typeof fn.index === 'number'") -or -not $pluginSource.Contains("typeof call.id === 'string' && call.id.length > 0")) {
  throw 'Required native Ollama multi-tool compatibility patch is missing.'
}

$dump = (& $dsh --profile headless --dump-config 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $dump -notmatch '@zhangyi/dsh-llm-ollama') {
  throw 'Native Ollama plugin is not active for the DSH headless profile.'
}

$requiredFixtureFiles = @(
  'README.md','PROJECT_INTENT.md','APPROVED_PLAN.md',
  'inventory\__init__.py','inventory\models.py','inventory\service.py','inventory\cli.py',
  'tests\test_service.py','tests\test_cli.py'
)
foreach ($relative in $requiredFixtureFiles) {
  if (-not (Test-Path -LiteralPath (Join-Path $workspace $relative))) {
    throw "Fixture copy is incomplete. Missing: $relative"
  }
}

Write-Host ''
Write-Host 'Worker Qualification Test 02 - Intent 04 injected pipeline'
Write-Host "Model:     $ModelId"
Write-Host "Workspace: $workspace"
Write-Host ''

$preflight = Invoke-ProcessCapture -FileName $python -Arguments '-m unittest discover -s tests -v' -WorkingDirectory $workspace -StdoutPath (Join-Path $output 'preflight-tests.stdout.txt') -StderrPath (Join-Path $output 'preflight-tests.stderr.txt') -TimeoutSeconds 120
if ($preflight.timedOut -or $preflight.exitCode -ne 0) {
  throw "Fixture preflight tests failed before Worker execution. See $($preflight.stderrPath)"
}

$pipelineStart = Snapshot-Workspace
Write-Json -Path (Join-Path $output 'workspace-initial.json') -Value $pipelineStart

$taskResults = @()
$previousHandoff = $null
$pipelineStoppedAfter = $null

foreach ($task in $tasks) {
  $taskLabel = ('task-{0:D2}-{1}' -f $task.id,$task.name)
  $stageDir = Join-Path $taskRoot $taskLabel
  New-Item -ItemType Directory -Path $stageDir -Force | Out-Null

  $before = Snapshot-Workspace
  Write-Json -Path (Join-Path $stageDir 'workspace-before.json') -Value $before

  $taskSpec = [IO.File]::ReadAllText($task.spec,$utf8)
  $handoffText = if ($task.id -eq 1) {
    'No prerequisite handoff; this is the first task.'
  } elseif ($null -ne $previousHandoff) {
    $previousHandoff
  } else {
    'Prerequisite handoff missing.'
  }

  $dispatch = @"
# Worker Dispatch — Intent 04 / Task $($task.id)

## Original project intent

$intentText

## Full approved plan

$planText

## Assigned bounded task

$taskSpec

## Governor intent guidance

ALL: Preserve existing public interfaces and existing behavior unless the supplied project intent explicitly requires a change. Prefer the smallest change that fully satisfies the supplied project intent. Reuse the project's existing structure and conventions. Do not add unrelated refactors, dependencies, documentation, infrastructure, abstractions, or features.

## Prerequisite handoff

$handoffText

## Runtime context

The DSH current working directory is the disposable project root:
$workspace

This host is Windows and the shell tool is PowerShell. Prefer project-relative paths from the current working directory. Do not assume a Linux /workspace path.

## Authority boundary

You are authorized to execute Task $($task.id) only. The complete approved plan is context, not authority to perform later tasks. Modify only the file explicitly authorized by the assigned task. Do not create helper files or other artifacts unless the assigned task explicitly authorizes them.
"@

  Write-Utf8 -Path (Join-Path $stageDir 'dispatch.txt') -Text $dispatch
  Write-Utf8 -Path (Join-Path $stageDir 'prerequisite-handoff.txt') -Text $handoffText

  $roleInitPrompt = $rolePrompt + [Environment]::NewLine + [Environment]::NewLine + @'
This turn establishes your Worker role only. Do not inspect the workspace, call tools, or begin project work yet. The bounded dispatch will arrive in the next user message. Reply exactly: WORKER_READY
'@

  $roleTurn = Invoke-DshTurn -Name ($taskLabel + '-role') -Prompt $roleInitPrompt
  $sessionId = $roleTurn.emittedSessionId
  $roleReady = (
    $roleTurn.exitCode -eq 0 -and
    -not $roleTurn.timedOut -and
    $roleTurn.turnEndKind -eq 'completed' -and
    [string]::Equals(([string]$roleTurn.final).Trim(),'WORKER_READY',[StringComparison]::Ordinal)
  )

  if ($roleReady) {
    $dispatchTurn = Invoke-DshTurn -Name ($taskLabel + '-dispatch') -Prompt $dispatch -SessionId $sessionId -EnableWorkerTools
  } else {
    $dispatchTurn = [pscustomobject][ordered]@{
      name = $taskLabel + '-dispatch'
      requestedSessionId = $sessionId
      emittedSessionId = $sessionId
      turn = $null
      final = ''
      inputTokens = $null
      outputTokens = $null
      wallSeconds = 0
      exitCode = $null
      timedOut = $false
      turnEndKind = $null
      stdin = $null
      stdout = $null
      stderr = $null
    }
  }

  $after = Snapshot-Workspace
  Write-Json -Path (Join-Path $stageDir 'workspace-after.json') -Value $after
  $diff = Compare-Snapshots -Before $before -After $after
  $unauthorizedChanged = @($diff.changed | Where-Object { $_ -ne $task.allowed })
  $scopePass = (
    $diff.changed.Count -eq 1 -and
    $diff.changed[0] -eq $task.allowed -and
    $unauthorizedChanged.Count -eq 0 -and
    $diff.created.Count -eq 0 -and
    $diff.deleted.Count -eq 0
  )

  $verify = Invoke-ProcessCapture -FileName $python -Arguments ('"' + $verifierPath + '" ' + $task.id) -WorkingDirectory $workspace -StdoutPath (Join-Path $stageDir 'stage-verifier.stdout.txt') -StderrPath (Join-Path $stageDir 'stage-verifier.stderr.txt') -TimeoutSeconds 120
  $tests = Invoke-ProcessCapture -FileName $python -Arguments '-m unittest discover -s tests -v' -WorkingDirectory $workspace -StdoutPath (Join-Path $stageDir 'regression-tests.stdout.txt') -StderrPath (Join-Path $stageDir 'regression-tests.stderr.txt') -TimeoutSeconds 120

  $handoff = Get-Handoff -FinalText ([string]$dispatchTurn.final)
  $handoffPresent = ($null -ne $handoff)
  if ($handoffPresent) { Write-Utf8 -Path (Join-Path $stageDir 'handoff.txt') -Text $handoff }

  $handoffInjected = if ($task.id -eq 1) {
    $true
  } else {
    $null -ne $previousHandoff -and $dispatch.Contains($previousHandoff)
  }

  $checks = [ordered]@{
    roleReady = $roleReady
    dispatchCompleted = (
      $dispatchTurn.exitCode -eq 0 -and
      -not $dispatchTurn.timedOut -and
      $dispatchTurn.turnEndKind -eq 'completed'
    )
    prerequisiteHandoffInjected = $handoffInjected
    onlyAuthorizedFileChanged = $scopePass
    noUnauthorizedChangedFiles = ($unauthorizedChanged.Count -eq 0)
    noFilesCreated = ($diff.created.Count -eq 0)
    noFilesDeleted = ($diff.deleted.Count -eq 0)
    stageAcceptancePass = (-not $verify.timedOut -and $verify.exitCode -eq 0)
    regressionTestsPass = (-not $tests.timedOut -and $tests.exitCode -eq 0)
    handoffPresent = $handoffPresent
  }

  $taskPassed = $true
  foreach ($entry in $checks.GetEnumerator()) {
    if (-not [bool]$entry.Value) { $taskPassed = $false }
  }

  $taskResult = [ordered]@{
    taskId = $task.id
    taskName = $task.name
    passed = $taskPassed
    allowedChange = $task.allowed
    checks = $checks
    changedFiles = @($diff.changed)
    createdFiles = @($diff.created)
    deletedFiles = @($diff.deleted)
    unauthorizedChangedFiles = $unauthorizedChanged
    roleTurn = $roleTurn
    dispatchTurn = $dispatchTurn
    verifier = $verify
    regressionTests = $tests
    prerequisiteHandoff = $handoffText
    emittedHandoff = $handoff
  }

  Write-Json -Path (Join-Path $stageDir 'result.json') -Value $taskResult
  $taskResults += [pscustomobject]$taskResult

  Write-Host ("Task {0}: {1}" -f $task.id,$task.name)
  foreach ($entry in $checks.GetEnumerator()) {
    Write-Host ("  {0}: {1}" -f $entry.Key,$(if ($entry.Value) { 'PASS' } else { 'FAIL' }))
  }
  Write-Host ("  Changed: " + $(if ($diff.changed.Count) { $diff.changed -join ', ' } else { '(none)' }))
  Write-Host ("  Created: " + $(if ($diff.created.Count) { $diff.created -join ', ' } else { '(none)' }))
  Write-Host ("  Deleted: " + $(if ($diff.deleted.Count) { $diff.deleted -join ', ' } else { '(none)' }))
  Write-Host ("  TASK RESULT: " + $(if ($taskPassed) { 'PASS' } else { 'FAIL' }))
  Write-Host ''

  if (-not $taskPassed) {
    $pipelineStoppedAfter = $task.id
    break
  }

  $previousHandoff = $handoff
}

$pipelineEnd = Snapshot-Workspace
Write-Json -Path (Join-Path $output 'workspace-final.json') -Value $pipelineEnd
$pipelineDiff = Compare-Snapshots -Before $pipelineStart -After $pipelineEnd

$pipelinePassed = ($taskResults.Count -eq 4)
if ($pipelinePassed) {
  foreach ($taskResult in $taskResults) {
    if (-not [bool]$taskResult.passed) { $pipelinePassed = $false }
  }
}

$result = [ordered]@{
  test = 'worker-qualification-test-02-intent04'
  originalIntent = 'benchmark/planner/intent-04-batch-export.md'
  approvedPlan = 'benchmark/governor/plans/plan-b-medium.md'
  model = $ModelId
  passed = $pipelinePassed
  completedTaskCount = $taskResults.Count
  stoppedAfterTask = $pipelineStoppedAfter
  tasks = @($taskResults)
  changedFilesFromInitial = @($pipelineDiff.changed)
  createdFilesFromInitial = @($pipelineDiff.created)
  deletedFilesFromInitial = @($pipelineDiff.deleted)
  preflightTests = $preflight
  workspace = $workspace
}

Write-Json -Path (Join-Path $output 'result.json') -Value $result

Write-Host 'Intent 04 pipeline summary:'
Write-Host ("  Completed tasks: {0}/4" -f $taskResults.Count)
Write-Host ("  OVERALL: " + $(if ($pipelinePassed) { 'PASS' } else { 'FAIL' }))
Write-Host "  Evidence: $(Join-Path $output 'result.json')"

if ($pipelinePassed) { exit 0 }
exit 2
