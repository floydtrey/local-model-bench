param(
  [string]$OutputRoot = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\tester-qualification-v1\qwen35-quick-v1'),
  [int]$WallSecondsPerTurn = 300
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$toolPatch = Join-Path $repo 'benchmark\dsh\worker-qualification-v1.patch.yml'
$modelPatch = Join-Path $repo 'benchmark\dsh\smoke-qwen35-9b.patch.yml'
$rolePromptPath = Join-Path $repo 'benchmark\tester\ROLE_PROMPT.md'
$fixtureRoot = Join-Path $repo 'benchmark\tester\fixtures'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$model = 'qwen3.5:9b'
$utf8 = [Text.UTF8Encoding]::new($false)

$cases = @(
  [pscustomobject]@{ id='A'; dir='case-a'; expectedPreflight=0; expectedFinal=0; expectedResult='PASS'; requireTestChange=$false },
  [pscustomobject]@{ id='C'; dir='case-c'; expectedPreflight=0; expectedFinal=1; expectedResult='FAIL'; requireTestChange=$true },
  [pscustomobject]@{ id='D'; dir='case-d'; expectedPreflight=1; expectedFinal=0; expectedResult='PASS'; requireTestChange=$true }
)

foreach ($required in @($dsh,$basePatch,$toolPatch,$modelPatch,$rolePromptPath,$fixtureRoot)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required path: $required" }
}
if ($WallSecondsPerTurn -lt 30) { throw 'WallSecondsPerTurn must be at least 30.' }

$output = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $output) { throw "Output directory already exists: $output" }
New-Item -ItemType Directory -Path $output -Force | Out-Null

$env:DSH_HOME = $dshHome
$env:DSH_TELEMETRY_DISABLED = '1'

function Write-Utf8([string]$Path,[string]$Text) {
  [IO.File]::WriteAllBytes($Path,$utf8.GetBytes($Text))
}

function Write-Json([string]$Path,$Value) {
  Write-Utf8 -Path $Path -Text ($Value | ConvertTo-Json -Depth 20)
}

function Hash-File([string]$Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Snapshot-Workspace([string]$Workspace) {
  $snapshot = [ordered]@{}
  Get-ChildItem -LiteralPath $Workspace -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($Workspace.Length).TrimStart('\')
    if ($relative -match '(^|\\)__pycache__\\' -or $relative -match '\.pyc$') { return }
    $snapshot[$relative] = Hash-File $_.FullName
  }
  return $snapshot
}

function Compare-Snapshots($Before,$After) {
  $changed=@(); $created=@(); $deleted=@()
  foreach ($key in $Before.Keys) {
    if (-not $After.Contains($key)) { $deleted += $key }
    elseif ($Before[$key] -ne $After[$key]) { $changed += $key }
  }
  foreach ($key in $After.Keys) {
    if (-not $Before.Contains($key)) { $created += $key }
  }
  return [pscustomobject]@{changed=@($changed);created=@($created);deleted=@($deleted)}
}

function Invoke-ProcessCapture {
  param(
    [string]$FileName,[string]$Arguments,[string]$WorkingDirectory,
    [string]$StdoutPath,[string]$StderrPath,[int]$TimeoutSeconds=120
  )
  $psi=[Diagnostics.ProcessStartInfo]::new()
  $psi.FileName=$FileName
  $psi.Arguments=$Arguments
  $psi.WorkingDirectory=$WorkingDirectory
  $psi.EnvironmentVariables['PYTHONPATH']=$WorkingDirectory
  $psi.UseShellExecute=$false
  $psi.CreateNoWindow=$true
  $psi.RedirectStandardOutput=$true
  $psi.RedirectStandardError=$true
  $proc=[Diagnostics.Process]::new()
  $proc.StartInfo=$psi
  $started=Get-Date
  [void]$proc.Start()
  $stdoutTask=$proc.StandardOutput.ReadToEndAsync()
  $stderrTask=$proc.StandardError.ReadToEndAsync()
  $timedOut=-not $proc.WaitForExit($TimeoutSeconds*1000)
  if($timedOut){
    try{ & taskkill.exe /PID $proc.Id /T /F *> $null }catch{}
    try{ $proc.WaitForExit() }catch{}
  }
  $stdout=$stdoutTask.GetAwaiter().GetResult()
  $stderr=$stderrTask.GetAwaiter().GetResult()
  $ended=Get-Date
  Write-Utf8 $StdoutPath $stdout
  Write-Utf8 $StderrPath $stderr
  return [pscustomobject]@{
    exitCode=$(if($timedOut){$null}else{$proc.ExitCode})
    timedOut=$timedOut
    wallSeconds=[math]::Round(($ended-$started).TotalSeconds,3)
    stdout=$stdout
    stderr=$stderr
  }
}

function Invoke-DshTurn {
  param(
    [string]$Name,[string]$Prompt,[string]$Workspace,[string]$TurnRoot,
    [string]$SessionId='',[switch]$EnableTools
  )

  $turnDir=Join-Path $TurnRoot $Name
  New-Item -ItemType Directory -Path $turnDir -Force | Out-Null
  $stdinPath=Join-Path $turnDir 'stdin.txt'
  $stdoutPath=Join-Path $turnDir 'stdout.jsonl'
  $stderrPath=Join-Path $turnDir 'stderr.txt'
  Write-Utf8 $stdinPath $Prompt

  $resume=''
  if($SessionId){$resume=' --session-id "'+$SessionId+'"'}

  $patchArgs=' --patch "'+$basePatch+'"'
  if($EnableTools){$patchArgs+=' --patch "'+$toolPatch+'"'}
  $patchArgs+=' --patch "'+$modelPatch+'"'

  $nativeCommand='"'+$dsh+'" --profile headless'+$patchArgs+' --json'+$resume+' -'

  $psi=[Diagnostics.ProcessStartInfo]::new()
  $psi.FileName='cmd.exe'
  $psi.Arguments='/d /s /c "'+$nativeCommand+'"'
  $psi.WorkingDirectory=$Workspace
  $psi.UseShellExecute=$false
  $psi.CreateNoWindow=$true
  $psi.RedirectStandardInput=$true
  $psi.RedirectStandardOutput=$true
  $psi.RedirectStandardError=$true

  $proc=[Diagnostics.Process]::new()
  $proc.StartInfo=$psi
  $started=Get-Date
  [void]$proc.Start()

  $stdoutTask=$proc.StandardOutput.ReadToEndAsync()
  $stderrTask=$proc.StandardError.ReadToEndAsync()
  $proc.StandardInput.Write($Prompt)
  $proc.StandardInput.Close()

  $timedOut=-not $proc.WaitForExit($WallSecondsPerTurn*1000)
  if($timedOut){
    try{ & taskkill.exe /PID $proc.Id /T /F *> $null }catch{}
    try{ $proc.WaitForExit() }catch{}
  }

  $stdout=$stdoutTask.GetAwaiter().GetResult()
  $stderr=$stderrTask.GetAwaiter().GetResult()
  $ended=Get-Date
  Write-Utf8 $stdoutPath $stdout
  Write-Utf8 $stderrPath $stderr

  $session=$null; $final=''; $inputTokens=$null; $outputTokens=$null; $turnEndKind=$null
  foreach($line in ($stdout -split "\r?\n")){
    if(-not $line.Trim()){continue}
    try{$event=$line|ConvertFrom-Json}catch{continue}
    if($event.type -eq 'session' -and $event.sessionId){$session=[string]$event.sessionId}
    if($event.type -eq 'final'){$final=[string]$event.text}
    if($event.type -eq 'status' -and $event.phase -eq 'step_end' -and $event.usage){
      $inputTokens=$event.usage.inputTokens; $outputTokens=$event.usage.outputTokens
    }
    if($event.type -eq 'status' -and $event.phase -eq 'turn_end' -and $event.reason){
      $turnEndKind=$event.reason.kind
    }
  }

  $record=[ordered]@{
    name=$Name
    requestedSessionId=$(if($SessionId){$SessionId}else{$null})
    emittedSessionId=$session
    final=$final
    inputTokens=$inputTokens
    outputTokens=$outputTokens
    wallSeconds=[math]::Round(($ended-$started).TotalSeconds,3)
    exitCode=$(if($timedOut){$null}else{$proc.ExitCode})
    timedOut=$timedOut
    turnEndKind=$turnEndKind
    stdout=$stdoutPath
    stderr=$stderrPath
  }
  Write-Json (Join-Path $turnDir 'turn.json') $record
  return [pscustomobject]$record
}

# Qualified runtime checks reused from Worker qualification.
try{$tags=Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5}catch{throw 'Ollama is not reachable.'}
if(@($tags.models.name) -notcontains $model){throw "Required model is not installed: $model"}

$dshVersion=(& $dsh --version 2>&1 | Out-String).Trim()
if($dshVersion -ne '0.1.6-alpha.2'){throw "Tester qualification requires DSH 0.1.6-alpha.2; found '$dshVersion'."}

$pluginRoot=Join-Path $dshHome 'profiles\headless\node_modules\@zhangyi\dsh-llm-ollama'
$pluginPackage=Get-Content -LiteralPath (Join-Path $pluginRoot 'package.json') -Raw | ConvertFrom-Json
if([string]$pluginPackage.version -ne '0.1.17'){throw "Tester qualification requires dsh-llm-ollama 0.1.17."}
$pluginSource=[IO.File]::ReadAllText((Join-Path $pluginRoot 'lib\index.js'),$utf8)
if(-not $pluginSource.Contains("typeof fn.index === 'number'") -or -not $pluginSource.Contains("typeof call.id === 'string' && call.id.length > 0")){
  throw 'Required native Ollama multi-tool compatibility patch is missing.'
}

$python=(Get-Command python.exe -ErrorAction Stop).Source
$rolePrompt=[IO.File]::ReadAllText($rolePromptPath,$utf8)
$results=@()

foreach($case in $cases){
  $caseOut=Join-Path $output ('case-'+$case.id.ToLowerInvariant())
  $workspace=Join-Path $caseOut 'workspace'
  $turnRoot=Join-Path $caseOut 'turns'
  New-Item -ItemType Directory -Path $workspace -Force | Out-Null
  New-Item -ItemType Directory -Path $turnRoot -Force | Out-Null

  $source=Join-Path $fixtureRoot $case.dir
  Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $workspace -Recurse -Force

  $intent=[IO.File]::ReadAllText((Join-Path $workspace 'PROJECT_INTENT.md'),$utf8)
  $plan=[IO.File]::ReadAllText((Join-Path $workspace 'APPROVED_PLAN.md'),$utf8)
  $task=[IO.File]::ReadAllText((Join-Path $workspace 'ASSIGNED_TASK.md'),$utf8)
  $handoff=[IO.File]::ReadAllText((Join-Path $workspace 'WORKER_HANDOFF.md'),$utf8)

  $preflight=Invoke-ProcessCapture -FileName $python -Arguments '-m unittest discover -s tests -v' -WorkingDirectory $workspace -StdoutPath (Join-Path $caseOut 'preflight.stdout.txt') -StderrPath (Join-Path $caseOut 'preflight.stderr.txt')
  $preflightMatched=($preflight.exitCode -eq $case.expectedPreflight -and -not $preflight.timedOut)

  $before=Snapshot-Workspace $workspace
  Write-Json (Join-Path $caseOut 'workspace-before.json') $before

  $roleInit=$rolePrompt+[Environment]::NewLine+[Environment]::NewLine+@'
This turn establishes your Tester role only. Do not inspect the workspace, call tools, or begin testing yet. The completed Worker task will arrive in the next user message. Reply exactly: TESTER_READY
'@
  $roleTurn=Invoke-DshTurn -Name 'role' -Prompt $roleInit -Workspace $workspace -TurnRoot $turnRoot
  $sessionId=$roleTurn.emittedSessionId

  if(-not $sessionId -or $roleTurn.exitCode -ne 0 -or $roleTurn.timedOut -or $roleTurn.turnEndKind -ne 'completed' -or ([string]$roleTurn.final).Trim() -ne 'TESTER_READY'){
    $caseResult=[ordered]@{case=$case.id;passed=$false;terminal='role_failure';preflightMatched=$preflightMatched;roleTurn=$roleTurn}
    Write-Json (Join-Path $caseOut 'result.json') $caseResult
    $results += [pscustomobject]$caseResult
    continue
  }

  $dispatch=@"
# Tester Dispatch — Case $($case.id)

## Original project intent

$intent

## Full approved plan

$plan

## Completed Worker task

$task

## Worker handoff

$handoff

## Runtime context

The current working directory is the disposable project root:
$workspace

This host is Windows and the shell tool is PowerShell.

## Tester authority

Evaluate the completed Worker task only.
You may read any project file and run focused tests.
You may create, modify, or remove files only under tests\ when needed to establish valid coverage.
Do not modify production code or project requirements.
Use actual deterministic test execution as evidence.
Follow the Tester role contract exactly, including the required final result line.
"@

  Write-Utf8 (Join-Path $caseOut 'dispatch.txt') $dispatch
  $dispatchTurn=Invoke-DshTurn -Name 'dispatch' -Prompt $dispatch -Workspace $workspace -TurnRoot $turnRoot -SessionId $sessionId -EnableTools

  $after=Snapshot-Workspace $workspace
  Write-Json (Join-Path $caseOut 'workspace-after.json') $after
  $diff=Compare-Snapshots $before $after

  $allChanged=@($diff.changed)+@($diff.created)+@($diff.deleted)
  $nonTestChanges=@($allChanged | Where-Object { $_ -notmatch '^tests\\' })
  $testChanges=@($allChanged | Where-Object { $_ -match '^tests\\' })

  $finalTests=Invoke-ProcessCapture -FileName $python -Arguments '-m unittest discover -s tests -v' -WorkingDirectory $workspace -StdoutPath (Join-Path $caseOut 'final-tests.stdout.txt') -StderrPath (Join-Path $caseOut 'final-tests.stderr.txt')
  $finalMatched=($finalTests.exitCode -eq $case.expectedFinal -and -not $finalTests.timedOut)

  $finalText=([string]$dispatchTurn.final).Trim()
  $resultLineOk=$finalText.EndsWith("Tester result: $($case.expectedResult)")
  $ranTestTool=(
    (Get-Content -LiteralPath $dispatchTurn.stdout -Raw) -match '"tool":"pwsh"' -and
    (Get-Content -LiteralPath $dispatchTurn.stdout -Raw) -match '(?i)unittest|pytest'
  )
  $testChangeOk=if($case.requireTestChange){$testChanges.Count -gt 0}else{$testChanges.Count -eq 0}
  $failFieldsOk=$true
  if($case.expectedResult -eq 'FAIL'){
    $failFieldsOk=($finalText -match '(?im)^Observed failure:' -and $finalText -match '(?im)^Repair criteria:')
  }

  $dispatchCompleted=($dispatchTurn.exitCode -eq 0 -and -not $dispatchTurn.timedOut -and $dispatchTurn.turnEndKind -eq 'completed')
  $passed=(
    $preflightMatched -and
    $dispatchCompleted -and
    $nonTestChanges.Count -eq 0 -and
    $testChangeOk -and
    $finalMatched -and
    $resultLineOk -and
    $ranTestTool -and
    $failFieldsOk
  )

  $caseResult=[ordered]@{
    case=$case.id
    passed=$passed
    expectedResult=$case.expectedResult
    preflightMatched=$preflightMatched
    dispatchCompleted=$dispatchCompleted
    ranTestTool=$ranTestTool
    nonTestChanges=@($nonTestChanges)
    testChanges=@($testChanges)
    finalTestsMatched=$finalMatched
    resultLineOk=$resultLineOk
    failFieldsOk=$failFieldsOk
    roleTurn=$roleTurn
    dispatchTurn=$dispatchTurn
    finalTests=$finalTests
  }
  Write-Json (Join-Path $caseOut 'result.json') $caseResult
  $results += [pscustomobject]$caseResult

  Write-Host ''
  Write-Host ("Tester Case {0}: {1}" -f $case.id,$case.expectedResult)
  Write-Host ("  Result: " + $(if($passed){'PASS'}else{'FAIL'}))
  Write-Host ("  Test changes: " + $(if($testChanges.Count){$testChanges -join ', '}else{'(none)'}))
  Write-Host ("  Non-test changes: " + $(if($nonTestChanges.Count){$nonTestChanges -join ', '}else{'(none)'}))
}

$overall=($results.Count -eq $cases.Count)
foreach($r in $results){if(-not [bool]$r.passed){$overall=$false}}

$summary=[ordered]@{
  test='tester-qualification-quick-v1'
  model=$model
  passed=$overall
  cases=@($results)
}
Write-Json (Join-Path $output 'result.json') $summary

Write-Host ''
Write-Host 'Tester Qualification Quick v1'
Write-Host "Model: $model"
Write-Host ("Cases passed: {0}/{1}" -f (@($results|Where-Object{$_.passed}).Count),$cases.Count)
Write-Host ("OVERALL TESTER RESULT: " + $(if($overall){'PASS'}else{'FAIL'}))
Write-Host "Evidence: $(Join-Path $output 'result.json')"

if($overall){exit 0}
exit 2
