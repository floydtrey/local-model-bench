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
$criteriaPath = Join-Path $repo 'benchmark\worker\intent04\ASSESSOR_CRITERIA.json'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$utf8 = [Text.UTF8Encoding]::new($false)

$tasks = @(
  [pscustomobject]@{
    id = 1
    name = 'register-export-csv'
    spec = (Join-Path $repo 'benchmark\worker\intent04\TASK_01.md')
    allowed = 'inventory\cli.py'
    gold = (Join-Path $repo 'benchmark\worker\intent04\gold\task-01\inventory\cli.py')
    goldHandoff = 'Handoff note: Qualification recovery checkpoint. Task 1 parser surface is in the accepted state: export-csv is registered with --include-inactive defaulting false and optional --output parsing. CSV behavior is not implemented yet.'
  },
  [pscustomobject]@{
    id = 2
    name = 'csv-retrieval-formatting'
    spec = (Join-Path $repo 'benchmark\worker\intent04\TASK_02.md')
    allowed = 'inventory\cli.py'
    gold = (Join-Path $repo 'benchmark\worker\intent04\gold\task-02\inventory\cli.py')
    goldHandoff = 'Handoff note: Qualification recovery checkpoint. Task 2 accepted state uses list_items(include_inactive=...) and the standard-library csv module to emit exact CSV to stdout with lowercase booleans and correct escaping. --output file writing is not implemented yet.'
  },
  [pscustomobject]@{
    id = 3
    name = 'file-output-errors'
    spec = (Join-Path $repo 'benchmark\worker\intent04\TASK_03.md')
    allowed = 'inventory\cli.py'
    gold = (Join-Path $repo 'benchmark\worker\intent04\gold\task-03\inventory\cli.py')
    goldHandoff = 'Handoff note: Qualification recovery checkpoint. Task 3 accepted state preserves stdout export and existing list behavior, writes --output CSV to file without stdout leakage, and reports file-write failures to stderr with non-zero status.'
  }
)

$required = @(
  $dsh,$basePatch,$workerPatch,$modelPatch,$rolePromptPath,$fixtureSource,
  $intentPath,$planPath,$verifierPath,$criteriaPath
)
$required += @($tasks | ForEach-Object { $_.spec })
$required += @($tasks | ForEach-Object { $_.gold })

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
$criteria = Get-Content -LiteralPath $criteriaPath -Raw | ConvertFrom-Json
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
  Write-Utf8 -Path $Path -Text ($Value | ConvertTo-Json -Depth 24)
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

function Backup-Workspace {
  param([Parameter(Mandatory=$true)][string]$Destination)
  New-Item -ItemType Directory -Path $Destination -Force | Out-Null
  Get-ChildItem -LiteralPath $workspace -Force | Copy-Item -Destination $Destination -Recurse -Force
}

function Remove-PythonCache {
  Get-ChildItem -LiteralPath $workspace -Directory -Recurse -Force |
    Where-Object { $_.Name -eq '__pycache__' } |
    Sort-Object FullName -Descending |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  Get-ChildItem -LiteralPath $workspace -File -Recurse -Force |
    Where-Object { $_.Extension -eq '.pyc' } |
    Remove-Item -Force -ErrorAction SilentlyContinue
}

function Restore-QualificationCheckpoint {
  param(
    [Parameter(Mandatory=$true)][string]$BaselineDirectory,
    [Parameter(Mandatory=$true)]$Task
  )

  Get-ChildItem -LiteralPath $workspace -Force | Remove-Item -Recurse -Force
  Get-ChildItem -LiteralPath $BaselineDirectory -Force | Copy-Item -Destination $workspace -Recurse -Force

  $goldDestination = Join-Path $workspace $Task.allowed
  Copy-Item -LiteralPath $Task.gold -Destination $goldDestination -Force
  Remove-PythonCache
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

function Invoke-StageVerifier {
  param(
    [Parameter(Mandatory=$true)][int]$TaskId,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
    [Parameter(Mandatory=$true)][string]$Label
  )

  $stdoutPath = Join-Path $EvidenceDirectory ($Label + '-verifier.stdout.txt')
  $stderrPath = Join-Path $EvidenceDirectory ($Label + '-verifier.stderr.txt')
  $run = Invoke-ProcessCapture -FileName $python -Arguments ('"' + $verifierPath + '" ' + $TaskId + ' --json') -WorkingDirectory $workspace -StdoutPath $stdoutPath -StderrPath $stderrPath -TimeoutSeconds 120

  if ($run.timedOut) { throw "Deterministic verifier timed out for Task $TaskId." }

  $parsed = $null
  try {
    $parsed = $run.stdout.Trim() | ConvertFrom-Json
  } catch {
    throw "Deterministic verifier did not emit parseable JSON for Task $TaskId. See $stdoutPath and $stderrPath"
  }

  return [pscustomobject]@{
    process = $run
    result = $parsed
  }
}

function Invoke-RegressionSuite {
  param(
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
    [Parameter(Mandatory=$true)][string]$Label
  )

  return Invoke-ProcessCapture -FileName $python -Arguments '-m unittest discover -s tests -v' -WorkingDirectory $workspace -StdoutPath (Join-Path $EvidenceDirectory ($Label + '-regression.stdout.txt')) -StderrPath (Join-Path $EvidenceDirectory ($Label + '-regression.stderr.txt')) -TimeoutSeconds 120
}

function Assess-WorkerAttempt {
  param(
    [Parameter(Mandatory=$true)]$Task,
    [Parameter(Mandatory=$true)]$Before,
    [Parameter(Mandatory=$true)]$Turn,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
    [Parameter(Mandatory=$true)][string]$Label,
    [Parameter(Mandatory=$true)][bool]$HandoffInjected
  )

  $after = Snapshot-Workspace
  Write-Json -Path (Join-Path $EvidenceDirectory ($Label + '-workspace-after.json')) -Value $after
  $diff = Compare-Snapshots -Before $Before -After $after

  $unauthorizedChanged = @($diff.changed | Where-Object { $_ -ne $Task.allowed })
  $scopePass = (
    $diff.changed.Count -eq 1 -and
    $diff.changed[0] -eq $Task.allowed -and
    $unauthorizedChanged.Count -eq 0 -and
    $diff.created.Count -eq 0 -and
    $diff.deleted.Count -eq 0
  )

  $verify = Invoke-StageVerifier -TaskId $Task.id -EvidenceDirectory $EvidenceDirectory -Label $Label
  $tests = Invoke-RegressionSuite -EvidenceDirectory $EvidenceDirectory -Label $Label
  $handoff = Get-Handoff -FinalText ([string]$Turn.final)
  $handoffPresent = ($null -ne $handoff)

  $dispatchCompleted = (
    $Turn.exitCode -eq 0 -and
    -not $Turn.timedOut -and
    $Turn.turnEndKind -eq 'completed'
  )

  $checks = [ordered]@{
    dispatchCompleted = $dispatchCompleted
    prerequisiteHandoffInjected = $HandoffInjected
    onlyAuthorizedFileChanged = $scopePass
    noUnauthorizedChangedFiles = ($unauthorizedChanged.Count -eq 0)
    noFilesCreated = ($diff.created.Count -eq 0)
    noFilesDeleted = ($diff.deleted.Count -eq 0)
    stageAcceptancePass = ([bool]$verify.result.passed -and $verify.process.exitCode -eq 0)
    regressionTestsPass = (-not $tests.timedOut -and $tests.exitCode -eq 0)
    handoffPresent = $handoffPresent
  }

  $passed = $true
  foreach ($entry in $checks.GetEnumerator()) {
    if (-not [bool]$entry.Value) { $passed = $false }
  }

  return [pscustomobject][ordered]@{
    passed = $passed
    checks = $checks
    changedFiles = @($diff.changed)
    createdFiles = @($diff.created)
    deletedFiles = @($diff.deleted)
    unauthorizedChangedFiles = $unauthorizedChanged
    verifier = $verify
    regressionTests = $tests
    emittedHandoff = $handoff
  }
}

function Get-TrimmedEvidence {
  param(
    [AllowEmptyString()][string]$Text,
    [int]$MaxChars = 3000
  )
  if ([string]::IsNullOrWhiteSpace($Text)) { return '(no diagnostic text)' }
  $trimmed = $Text.Trim()
  if ($trimmed.Length -le $MaxChars) { return $trimmed }
  return $trimmed.Substring(0,$MaxChars) + [Environment]::NewLine + '[diagnostic truncated]'
}

function Get-Criterion {
  param([Parameter(Mandatory=$true)][string]$CheckId)
  $property = $criteria.checks.PSObject.Properties[$CheckId]
  if ($null -eq $property) { return $null }
  return $property.Value
}

function New-RepairPacket {
  param(
    [Parameter(Mandatory=$true)]$Task,
    [Parameter(Mandatory=$true)]$Assessment
  )

  $lines = New-Object System.Collections.Generic.List[string]
  [void]$lines.Add('# REPAIR_REQUIRED')
  [void]$lines.Add('')
  [void]$lines.Add("Assigned task: Intent 04 / Task $($Task.id) - $($Task.name)")
  [void]$lines.Add('')
  [void]$lines.Add('The deterministic assessor found the following acceptance problems. Repair only these failures while preserving requirements that are already satisfied.')
  [void]$lines.Add('')

  foreach ($failure in @($Assessment.verifier.result.failures)) {
    $checkId = [string]$failure.check_id
    $criterion = Get-Criterion -CheckId $checkId
    [void]$lines.Add("## $checkId")
    if ($null -ne $criterion) {
      [void]$lines.Add("Requirement: $($criterion.requirement_reference)")
    }
    [void]$lines.Add("Observed: $([string]$failure.observed)")
    if ($null -ne $criterion) {
      [void]$lines.Add("Required repair: $($criterion.repair_criterion)")
    } else {
      [void]$lines.Add('Required repair: Restore the assigned task acceptance behavior without expanding scope.')
    }
    [void]$lines.Add('')
  }

  if (-not [bool]$Assessment.checks.onlyAuthorizedFileChanged) {
    if ($Assessment.unauthorizedChangedFiles.Count -gt 0) {
      [void]$lines.Add('## Unauthorized changed paths')
      [void]$lines.Add('Observed: ' + ($Assessment.unauthorizedChangedFiles -join ', '))
      [void]$lines.Add('Required repair: ' + [string]$criteria.generic.scope_changed)
      [void]$lines.Add('')
    }
    if ($Assessment.createdFiles.Count -gt 0) {
      [void]$lines.Add('## Unauthorized created paths')
      [void]$lines.Add('Observed: ' + ($Assessment.createdFiles -join ', '))
      [void]$lines.Add('Required repair: ' + [string]$criteria.generic.scope_created)
      [void]$lines.Add('')
    }
    if ($Assessment.deletedFiles.Count -gt 0) {
      [void]$lines.Add('## Unauthorized deleted paths')
      [void]$lines.Add('Observed: ' + ($Assessment.deletedFiles -join ', '))
      [void]$lines.Add('Required repair: ' + [string]$criteria.generic.scope_deleted)
      [void]$lines.Add('')
    }
    if ($Assessment.changedFiles -notcontains $Task.allowed) {
      [void]$lines.Add('## Required authorized implementation change missing')
      [void]$lines.Add("Observed: $($Task.allowed) is not present in the final changed-file set for Task $($Task.id).")
      [void]$lines.Add("Required repair: place the assigned implementation in $($Task.allowed) and keep every other path at its pre-task state.")
      [void]$lines.Add('')
    }
  }

  if (-not [bool]$Assessment.checks.regressionTestsPass) {
    [void]$lines.Add('## Existing regression suite failed')
    [void]$lines.Add('Observed test evidence:')
    [void]$lines.Add('BEGIN_TEST_EVIDENCE')
    [void]$lines.Add((Get-TrimmedEvidence -Text ([string]$Assessment.regressionTests.stderr)))
    [void]$lines.Add('END_TEST_EVIDENCE')
    [void]$lines.Add('Required repair: ' + [string]$criteria.generic.regression)
    [void]$lines.Add('')
  }

  if (-not [bool]$Assessment.checks.handoffPresent) {
    [void]$lines.Add('## Completion handoff missing')
    [void]$lines.Add('Required repair: ' + [string]$criteria.generic.handoff)
    [void]$lines.Add('')
  }

  [void]$lines.Add('## Authority boundary')
  [void]$lines.Add("You remain authorized to modify only: $($Task.allowed)")
  [void]$lines.Add('Do not modify tests. Do not begin a later plan task. Do not create helper files.')
  [void]$lines.Add('')
  [void]$lines.Add('This is the single repair attempt for this qualification task. Use the current workspace state, make the smallest repair that satisfies the criteria above, run focused checks if useful, then stop.')
  [void]$lines.Add('Your final response must end with Handoff note: followed by the concise information needed by the next dependent Worker.')

  return ($lines -join [Environment]::NewLine)
}

function Get-TerminalCondition {
  param(
    [Parameter(Mandatory=$true)]$Turn,
    [Parameter(Mandatory=$true)][bool]$RoleReady
  )

  if (-not $RoleReady) { return 'role_init_failure' }
  if ($Turn.timedOut) { return 'worker_timeout' }
  if ($Turn.exitCode -ne 0 -or $Turn.turnEndKind -ne 'completed') {
    return 'runtime_or_interface_failure'
  }
  return 'completed'
}

try {
  $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
  throw 'Ollama is not reachable at http://127.0.0.1:11434.'
}
if (@($tags.models.name) -notcontains $ModelId) {
  throw "Required model is not installed: $ModelId"
}

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
Write-Host 'Worker Qualification Test 02 - Intent 04 deterministic-assessor pipeline'
Write-Host "Model:     $ModelId"
Write-Host "Workspace: $workspace"
Write-Host 'Repair cap: one deterministic repair attempt per task'
Write-Host ''

$preflight = Invoke-ProcessCapture -FileName $python -Arguments '-m unittest discover -s tests -v' -WorkingDirectory $workspace -StdoutPath (Join-Path $output 'preflight-tests.stdout.txt') -StderrPath (Join-Path $output 'preflight-tests.stderr.txt') -TimeoutSeconds 120
if ($preflight.timedOut -or $preflight.exitCode -ne 0) {
  throw "Fixture preflight tests failed before Worker execution. See $($preflight.stderrPath)"
}

$pipelineStart = Snapshot-Workspace
Write-Json -Path (Join-Path $output 'workspace-initial.json') -Value $pipelineStart

$taskResults = @()
$previousHandoff = $null
$failedTaskIds = @()
$repairedTaskCount = 0
$firstPassTaskCount = 0
$qualificationRecoveryCount = 0

foreach ($task in $tasks) {
  $taskLabel = ('task-{0:D2}-{1}' -f $task.id,$task.name)
  $stageDir = Join-Path $taskRoot $taskLabel
  $baselineDir = Join-Path $stageDir 'baseline-workspace'
  New-Item -ItemType Directory -Path $stageDir -Force | Out-Null

  $before = Snapshot-Workspace
  Write-Json -Path (Join-Path $stageDir 'workspace-before.json') -Value $before
  Backup-Workspace -Destination $baselineDir

  $taskSpec = [IO.File]::ReadAllText($task.spec,$utf8)
  $handoffText = if ($task.id -eq 1) {
    'No prerequisite handoff; this is the first task.'
  } elseif ($null -ne $previousHandoff) {
    $previousHandoff
  } else {
    throw "Harness error: Task $($task.id) has no prerequisite handoff."
  }

  $dispatch = @"
# Worker Dispatch - Intent 04 / Task $($task.id)

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

  $handoffInjected = if ($task.id -eq 1) { $true } else { $dispatch.Contains($handoffText) }
  $first = Assess-WorkerAttempt -Task $task -Before $before -Turn $dispatchTurn -EvidenceDirectory $stageDir -Label 'first-pass' -HandoffInjected $handoffInjected

  $repairAttempted = $false
  $repairPacket = $null
  $repairTurn = $null
  $repair = $null
  $finalAssessment = $first
  $terminalCondition = Get-TerminalCondition -Turn $dispatchTurn -RoleReady $roleReady

  if ($first.passed) {
    $firstPassTaskCount++
  } elseif ($roleReady -and [bool]$first.checks.dispatchCompleted -and [bool]$first.checks.prerequisiteHandoffInjected) {
    $repairAttempted = $true
    $repairPacket = New-RepairPacket -Task $task -Assessment $first
    Write-Utf8 -Path (Join-Path $stageDir 'repair-packet.md') -Text $repairPacket

    $repairTurn = Invoke-DshTurn -Name ($taskLabel + '-repair') -Prompt $repairPacket -SessionId $sessionId -EnableWorkerTools
    $repair = Assess-WorkerAttempt -Task $task -Before $before -Turn $repairTurn -EvidenceDirectory $stageDir -Label 'repair-pass' -HandoffInjected $handoffInjected
    $finalAssessment = $repair

    if ($repair.passed) {
      $repairedTaskCount++
      $terminalCondition = 'repaired'
    } else {
      $repairTerminal = Get-TerminalCondition -Turn $repairTurn -RoleReady $roleReady
      $terminalCondition = if ($repairTerminal -eq 'completed') { 'failed_after_repair' } else { $repairTerminal }
    }
  }

  $taskPassed = [bool]$finalAssessment.passed
  $acceptedHandoff = if ($taskPassed) { $finalAssessment.emittedHandoff } else { $null }
  $recoveryUsed = $false
  $nextTaskHandoff = $acceptedHandoff
  $goldVerification = $null
  $goldRegression = $null

  if (-not $taskPassed) {
    $failedTaskIds += $task.id

    if ($task.id -lt 3) {
      Restore-QualificationCheckpoint -BaselineDirectory $baselineDir -Task $task
      $goldVerification = Invoke-StageVerifier -TaskId $task.id -EvidenceDirectory $stageDir -Label 'gold-recovery'
      $goldRegression = Invoke-RegressionSuite -EvidenceDirectory $stageDir -Label 'gold-recovery'

      if (-not [bool]$goldVerification.result.passed -or $goldVerification.process.exitCode -ne 0 -or $goldRegression.timedOut -or $goldRegression.exitCode -ne 0) {
        throw "Gold qualification checkpoint failed validation for Task $($task.id)."
      }

      $recoveryUsed = $true
      $qualificationRecoveryCount++
      $nextTaskHandoff = [string]$task.goldHandoff
      Write-Utf8 -Path (Join-Path $stageDir 'qualification-recovery-handoff.txt') -Text $nextTaskHandoff
    }
  }

  if ($task.id -lt 3) {
    if ([string]::IsNullOrWhiteSpace([string]$nextTaskHandoff)) {
      throw "Harness error: no accepted or recovery handoff available after Task $($task.id)."
    }
    $previousHandoff = $nextTaskHandoff
  }

  $taskResult = [ordered]@{
    taskId = $task.id
    taskName = $task.name
    passed = $taskPassed
    firstPassPassed = [bool]$first.passed
    repairAttempted = $repairAttempted
    repairPassed = $(if ($repairAttempted) { [bool]$repair.passed } else { $null })
    terminalCondition = $terminalCondition
    qualificationRecoveryUsed = $recoveryUsed
    allowedChange = $task.allowed
    roleTurn = $roleTurn
    dispatchTurn = $dispatchTurn
    firstPass = $first
    repairPacket = $repairPacket
    repairTurn = $repairTurn
    repairPass = $repair
    acceptedHandoff = $acceptedHandoff
    nextTaskHandoff = $nextTaskHandoff
    goldVerification = $goldVerification
    goldRegression = $goldRegression
  }

  Write-Json -Path (Join-Path $stageDir 'result.json') -Value $taskResult
  $taskResults += [pscustomobject]$taskResult

  Write-Host ("Task {0}: {1}" -f $task.id,$task.name)
  Write-Host ("  First pass: {0}" -f $(if ($first.passed) { 'PASS' } else { 'FAIL' }))
  if ($repairAttempted) {
    Write-Host ("  Repair attempt: {0}" -f $(if ($repair.passed) { 'PASS' } else { 'FAIL' }))
  } else {
    Write-Host '  Repair attempt: (not used)'
  }
  Write-Host ("  Final task result: {0}" -f $(if ($taskPassed) { 'PASS' } else { 'FAIL' }))
  Write-Host ("  Terminal condition: {0}" -f $terminalCondition)
  Write-Host ("  Qualification recovery for next task: {0}" -f $(if ($recoveryUsed) { 'YES' } else { 'NO' }))
  Write-Host ("  Final changed: " + $(if ($finalAssessment.changedFiles.Count) { $finalAssessment.changedFiles -join ', ' } else { '(none)' }))
  Write-Host ("  Final created: " + $(if ($finalAssessment.createdFiles.Count) { $finalAssessment.createdFiles -join ', ' } else { '(none)' }))
  Write-Host ("  Final deleted: " + $(if ($finalAssessment.deletedFiles.Count) { $finalAssessment.deletedFiles -join ', ' } else { '(none)' }))
  Write-Host ''
}

$pipelineEnd = Snapshot-Workspace
Write-Json -Path (Join-Path $output 'workspace-final.json') -Value $pipelineEnd
$pipelineDiff = Compare-Snapshots -Before $pipelineStart -After $pipelineEnd

$pipelinePassed = ($failedTaskIds.Count -eq 0 -and $taskResults.Count -eq 3)

$result = [ordered]@{
  test = 'worker-qualification-test-02-intent04'
  architecture = 'deterministic-assessor-with-one-repair-v1'
  originalIntent = 'benchmark/planner/intent-04-batch-export.md'
  approvedPlan = 'benchmark/governor/plans/plan-b-medium.md'
  model = $ModelId
  passed = $pipelinePassed
  completedTaskCount = $taskResults.Count
  firstPassTaskCount = $firstPassTaskCount
  repairedTaskCount = $repairedTaskCount
  failedTaskIds = @($failedTaskIds)
  qualificationRecoveryCount = $qualificationRecoveryCount
  tasks = @($taskResults)
  testerTaskReserved = 'Approved Plan B Task 4 is reserved for the Tester role and is not part of Worker qualification.'
  changedFilesFromInitial = @($pipelineDiff.changed)
  createdFilesFromInitial = @($pipelineDiff.created)
  deletedFilesFromInitial = @($pipelineDiff.deleted)
  preflightTests = $preflight
  workspace = $workspace
}

Write-Json -Path (Join-Path $output 'result.json') -Value $result

Write-Host 'Intent 04 Worker qualification summary:'
Write-Host ("  Tasks attempted: {0}/3" -f $taskResults.Count)
Write-Host ("  First-pass tasks: {0}/3" -f $firstPassTaskCount)
Write-Host ("  Repaired tasks: {0}" -f $repairedTaskCount)
Write-Host ("  Failed tasks: " + $(if ($failedTaskIds.Count) { $failedTaskIds -join ', ' } else { '(none)' }))
Write-Host ("  Gold recoveries used only to continue qualification: {0}" -f $qualificationRecoveryCount)
Write-Host ("  OVERALL WORKER RESULT: " + $(if ($pipelinePassed) { 'PASS' } else { 'FAIL' }))
Write-Host "  Evidence: $(Join-Path $output 'result.json')"

if ($pipelinePassed) { exit 0 }
exit 2
