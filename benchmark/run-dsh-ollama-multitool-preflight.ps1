param(
  [string]$OutputDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\runtime-qualification\dsh-ollama-multitool-v1'),
  [int]$WallSeconds = 180
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$toolPatch = Join-Path $repo 'benchmark\dsh\ollama-multitool-preflight-v1.patch.yml'
$modelPatch = Join-Path $repo 'benchmark\dsh\smoke-qwen35-9b.patch.yml'
$pluginRoot = Join-Path $env:USERPROFILE '.dsh\profiles\headless\node_modules\@zhangyi\dsh-llm-ollama'
$pluginIndex = Join-Path $pluginRoot 'lib\index.js'
$pluginPackage = Join-Path $pluginRoot 'package.json'
$utf8 = [Text.UTF8Encoding]::new($false)

foreach ($required in @($dsh,$basePatch,$toolPatch,$modelPatch,$pluginIndex,$pluginPackage)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required path: $required" }
}
if ($WallSeconds -lt 30) { throw 'WallSeconds must be at least 30.' }

$dshVersion = (& $dsh --version 2>&1 | Out-String).Trim()
if ($dshVersion -ne '0.1.6-alpha.2') { throw "Expected DSH 0.1.6-alpha.2, found '$dshVersion'." }

$package = Get-Content -LiteralPath $pluginPackage -Raw | ConvertFrom-Json
if ([string]$package.version -ne '0.1.17') { throw "Expected dsh-llm-ollama 0.1.17, found '$($package.version)'." }

$pluginSource = [IO.File]::ReadAllText($pluginIndex,$utf8)
if (-not $pluginSource.Contains("typeof fn.index === 'number'") -or -not $pluginSource.Contains("typeof call.id === 'string' && call.id.length > 0")) {
  throw 'Required multi-tool compatibility patch is not present. Run patch-dsh-ollama-multitool.ps1 first.'
}

$output = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $output) { throw "Output directory already exists: $output" }
$workspace = Join-Path $output 'workspace'
New-Item -ItemType Directory -Path $workspace -Force | Out-Null

$nl = [Environment]::NewLine
[IO.File]::WriteAllText((Join-Path $workspace 'alpha.txt'),('ALPHA_7319' + $nl),$utf8)
[IO.File]::WriteAllText((Join-Path $workspace 'beta.txt'),('BETA_2846' + $nl),$utf8)
[IO.File]::WriteAllText((Join-Path $workspace 'gamma.txt'),('GAMMA_9052' + $nl),$utf8)

$prompt = @'
Use the read tool to read alpha.txt, beta.txt, and gamma.txt.

Important transport requirement for this preflight:
- issue all three read calls in the same assistant tool-calling response before waiting for any tool result;
- use one separate read call per file;
- do not use any other tool.

After all three results are available, reply exactly:
MULTITOOL_PASS ALPHA_7319 BETA_2846 GAMMA_9052
'@

$stdinPath = Join-Path $output 'stdin.txt'
$stdoutPath = Join-Path $output 'stdout.jsonl'
$stderrPath = Join-Path $output 'stderr.txt'
$resultPath = Join-Path $output 'result.json'
[IO.File]::WriteAllText($stdinPath,$prompt,$utf8)

$nativeCommand = '"' + $dsh + '" --profile headless --patch "' + $basePatch + '" --patch "' + $toolPatch + '" --patch "' + $modelPatch + '" --json -'

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
$proc.StandardInput.Write($prompt)
$proc.StandardInput.Close()

$timedOut = -not $proc.WaitForExit($WallSeconds * 1000)
if ($timedOut) {
  try { & taskkill.exe /PID $proc.Id /T /F *> $null } catch {}
  try { $proc.WaitForExit() } catch {}
}

$stdout = $stdoutTask.GetAwaiter().GetResult()
$stderr = $stderrTask.GetAwaiter().GetResult()
$ended = Get-Date

[IO.File]::WriteAllText($stdoutPath,$stdout,$utf8)
[IO.File]::WriteAllText($stderrPath,$stderr,$utf8)

$toolCalls = @()
$toolResults = @()
$final = ''
$turnEndKind = $null

foreach ($line in ($stdout -split "\r?\n")) {
  if (-not $line.Trim()) { continue }
  try { $event = $line | ConvertFrom-Json } catch { continue }

  if ($event.type -eq 'tool_call') { $toolCalls += $event }
  if ($event.type -eq 'tool_result') { $toolResults += $event }
  if ($event.type -eq 'final') { $final = [string]$event.text }
  if ($event.type -eq 'status' -and $event.phase -eq 'turn_end' -and $event.reason) {
    $turnEndKind = $event.reason.kind
  }
}

$paths = @()
$argumentsValid = $true

foreach ($call in $toolCalls) {
  if ([string]$call.tool -ne 'read') {
    $argumentsValid = $false
    continue
  }

  $inputObject = $call.input
  if ($null -eq $inputObject) {
    $argumentsValid = $false
    continue
  }

  $pathValue = [string]$inputObject.file_path
  if ([string]::IsNullOrWhiteSpace($pathValue)) {
    $argumentsValid = $false
    continue
  }

  $paths += [IO.Path]::GetFileName($pathValue)
}

$expectedPaths = @('alpha.txt','beta.txt','gamma.txt')
$missingExpected = @($expectedPaths | Where-Object { $paths -notcontains $_ })
$uniquePaths = @($paths | Sort-Object -Unique)

$threeDistinctReads = ($toolCalls.Count -eq 3 -and $uniquePaths.Count -eq 3 -and $missingExpected.Count -eq 0)
$failedToolResults = @($toolResults | Where-Object { [string]$_.status -ne 'completed' })
$threeCompletedResults = ($toolResults.Count -eq 3 -and $failedToolResults.Count -eq 0)
$terminalExact = [string]::Equals($final.Trim(),'MULTITOOL_PASS ALPHA_7319 BETA_2846 GAMMA_9052',[StringComparison]::Ordinal)

$checks = [ordered]@{
  processCompleted = (-not $timedOut -and $proc.ExitCode -eq 0)
  turnCompleted = ($turnEndKind -eq 'completed')
  exactlyThreeReadCalls = $threeDistinctReads
  toolArgumentsRemainSeparateAndValid = $argumentsValid
  exactlyThreeCompletedToolResults = $threeCompletedResults
  terminalAnswerExact = $terminalExact
  noMalformedArgumentError = ($stderr -notmatch 'Value looks like object|arguments.+must be an object')
}

$passed = $true
foreach ($entry in $checks.GetEnumerator()) {
  if (-not [bool]$entry.Value) { $passed = $false }
}

$result = [ordered]@{
  test = 'dsh-ollama-multitool-preflight-v1'
  scoredModelQualification = $false
  runtime = [ordered]@{
    dsh = $dshVersion
    plugin = [string]$package.version
    model = 'qwen3.5:9b'
  }
  passed = $passed
  checks = $checks
  toolCallCount = $toolCalls.Count
  toolResultCount = $toolResults.Count
  observedReadFiles = $paths
  final = $final
  exitCode = $(if ($timedOut) { $null } else { $proc.ExitCode })
  timedOut = $timedOut
  wallSeconds = [math]::Round(($ended-$started).TotalSeconds,3)
  stdout = $stdoutPath
  stderr = $stderrPath
}

[IO.File]::WriteAllText($resultPath,($result | ConvertTo-Json -Depth 12),$utf8)

Write-Host ''
Write-Host 'DSH native Ollama multi-tool preflight'
Write-Host "DSH:    $dshVersion"
Write-Host "Plugin: $($package.version)"
Write-Host 'Model:  qwen3.5:9b'
Write-Host ''
Write-Host 'Checks:'
foreach ($entry in $checks.GetEnumerator()) {
  Write-Host ("  {0}: {1}" -f $entry.Key,$(if ($entry.Value) { 'PASS' } else { 'FAIL' }))
}
Write-Host ''
Write-Host ("Observed read calls: " + $(if ($paths.Count) { $paths -join ', ' } else { '(none)' }))
Write-Host ("OVERALL PREFLIGHT: " + $(if ($passed) { 'PASS' } else { 'FAIL' }))
Write-Host "Evidence: $resultPath"

if ($stderr.Trim()) {
  Write-Host ''
  Write-Host 'stderr:'
  Write-Host $stderr.Trim()
}

if ($passed) { exit 0 }
exit 2
