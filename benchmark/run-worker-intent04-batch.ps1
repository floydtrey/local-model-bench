param(
  [string]$CandidatesFile = (Join-Path $PSScriptRoot 'worker\candidates-test02.csv'),
  [string]$OutputRoot = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\worker-qualification-v1\test-02-intent04-batch-v1'),
  [int]$WallSecondsPerTurn = 300,
  [switch]$Resume
)

$ErrorActionPreference = 'Stop'

$singleRunner = Join-Path $PSScriptRoot 'run-worker-intent04-candidate.ps1'
$settingsFile = Join-Path $env:USERPROFILE '.dsh\settings.yaml'
$utf8 = [Text.UTF8Encoding]::new($false)
$nl = [Environment]::NewLine

foreach ($required in @($CandidatesFile,$singleRunner,$settingsFile)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}
if ($WallSecondsPerTurn -lt 30) { throw 'WallSecondsPerTurn must be at least 30.' }

function Write-Utf8([string]$Path,[string]$Text) {
  [IO.File]::WriteAllBytes($Path,$utf8.GetBytes($Text))
}

function Yaml-Quote([string]$Text) {
  return "'" + $Text.Replace("'","''") + "'"
}

function Parse-Bool([string]$Value,[string]$Field,[string]$Model) {
  $n = ''
  if ($null -ne $Value) { $n = $Value.Trim().ToLowerInvariant() }
  if ($n -eq 'true') { return $true }
  if ($n -eq 'false') { return $false }
  throw "Candidate $Model has invalid $Field '$Value'."
}

function New-CandidatePatch($Candidate,[string]$PatchPath,[bool]$ThinkingCapable) {
  $model = Yaml-Quote ([string]$Candidate.model_id)
  $reason = ([string]$Candidate.reasoning_effort).Trim()
  $agentReason = ''
  $modelReason = ''
  if ($reason) {
    $q = Yaml-Quote $reason
    $agentReason = $nl + "    reasoningEffort: $q"
    $modelReason = $nl + "            reasoningEffort: $q"
  }
  $thinking = if ($ThinkingCapable) { 'true' } else { 'false' }

  $yaml = "- id: agent-default-model$nl  config:$nl    provider: role-benchmark-native$nl    model: $model$agentReason$nl$nl- id: llm-ollama$nl  config:$nl    providers:$nl      role-benchmark-native:$nl        displayName: Role Benchmark Native Ollama$nl        api: ollama-chat$nl        baseURL: http://127.0.0.1:11434$nl        keepAlive: 30m$nl        models:$nl          - id: $model$nl            name: $model$nl            contextWindow: $($Candidate.context_window)$nl            maxTokens: $($Candidate.max_tokens)$nl            thinkingCapable: $thinking$modelReason$nl$nl- id: llm-deepseek$nl  disabled: true$nl$nl- id: llm-pi-ai$nl  disabled: true$nl"
  Write-Utf8 $PatchPath $yaml
}

function Write-CandidateSettings($Candidate,[bool]$ThinkingCapable) {
  $model = Yaml-Quote ([string]$Candidate.model_id)
  $reason = ([string]$Candidate.reasoning_effort).Trim()
  $modelReason = ''
  if ($reason) { $modelReason = $nl + "          reasoningEffort: " + (Yaml-Quote $reason) }
  $thinking = if ($ThinkingCapable) { 'true' } else { 'false' }

  $yaml = "llm-ollama:$nl  providers:$nl    role-benchmark-native:$nl      displayName: Role Benchmark Native Ollama$nl      api: ollama-chat$nl      baseURL: http://127.0.0.1:11434$nl      keepAlive: 30m$nl      models:$nl        - id: $model$nl          name: $model$nl          contextWindow: $($Candidate.context_window)$nl          maxTokens: $($Candidate.max_tokens)$nl          thinkingCapable: $thinking$modelReason$nl"
  Write-Utf8 $settingsFile $yaml
}

function Set-SummaryRow([string]$Path,$Row) {
  $rows = @()
  if (Test-Path -LiteralPath $Path) {
    try {
      $rows = @(Import-Csv -LiteralPath $Path | Where-Object { $_.model_id -ne $Row.model_id })
    } catch {
      $rows = @()
    }
  }
  $rows += $Row
  $rows | Export-Csv -LiteralPath $Path -NoTypeInformation -Encoding UTF8
}

function Get-TaskPass($Result,[int]$TaskId) {
  $task = @($Result.tasks | Where-Object { [int]$_.taskId -eq $TaskId } | Select-Object -First 1)
  if ($task.Count -eq 0) { return '' }
  return [bool]$task[0].passed
}

$candidates = @(Import-Csv -LiteralPath $CandidatesFile)
if ($candidates.Count -lt 1) { throw 'No Worker Test 02 candidates found.' }

try {
  $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
  throw 'Ollama is not reachable.'
}
$installed = @{}
foreach ($m in @($tags.models)) { $installed[[string]$m.name] = $m }

$ollama = (Get-Command ollama.exe -ErrorAction Stop).Source
$settingsBackup = [IO.File]::ReadAllBytes($settingsFile)
$scratch = Join-Path $env:TEMP ('local-model-bench-worker-intent04-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$summaryPath = Join-Path $OutputRoot 'summary.csv'

try {
  foreach ($candidate in $candidates) {
    $modelId = [string]$candidate.model_id
    $fileName = [string]$candidate.file_name
    $thinkingCapable = Parse-Bool ([string]$candidate.thinking_capable) 'thinking_capable' $modelId
    $reasoning = ([string]$candidate.reasoning_effort).Trim()
    if (-not $reasoning) { $reasoning = 'default' }

    $modelOutput = Join-Path $OutputRoot $fileName

    if ($Resume -and (Test-Path -LiteralPath (Join-Path $modelOutput 'result.json'))) {
      Write-Host "Skipping completed: $modelId"
      continue
    }
    if ((Test-Path -LiteralPath $modelOutput) -and -not $Resume) {
      throw "Result directory already exists: $modelOutput"
    }

    if (-not $installed.ContainsKey($modelId)) {
      Write-Warning ("Skipping " + $modelId + ": not installed.")
      Set-SummaryRow $summaryPath ([pscustomobject][ordered]@{
        model_id=$modelId;reasoning=$reasoning;terminal_condition='not_installed';
        overall_pass='';completed_tasks='';stopped_after_task='';
        task1_pass='';task2_pass='';task3_pass='';
        final_changed_files='';final_created_files='';final_deleted_files='';exit_code=''
      })
      continue
    }

    Write-CandidateSettings $candidate $thinkingCapable
    $patchPath = Join-Path $scratch ($fileName + '.patch.yml')
    New-CandidatePatch $candidate $patchPath $thinkingCapable

    Write-Host ''
    Write-Host ('=' * 72)
    Write-Host "Worker Intent 04 candidate: $modelId"
    Write-Host "Reasoning: $reasoning"
    Write-Host ('=' * 72)

    $args = @{
      CandidatePatch = $patchPath
      ModelId = $modelId
      OutputDir = $modelOutput
      WallSecondsPerTurn = $WallSecondsPerTurn
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $singleRunner @args
    $runnerExit = $LASTEXITCODE

    $resultPath = Join-Path $modelOutput 'result.json'
    if (-not (Test-Path -LiteralPath $resultPath)) {
      Set-SummaryRow $summaryPath ([pscustomobject][ordered]@{
        model_id=$modelId;reasoning=$reasoning;terminal_condition='harness_error';
        overall_pass='';completed_tasks='';stopped_after_task='';
        task1_pass='';task2_pass='';task3_pass='';
        final_changed_files='';final_created_files='';final_deleted_files='';exit_code=$runnerExit
      })
    } else {
      $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
      $terminal = if ($runnerExit -eq 0) { 'completed' } else { 'candidate_fail' }

      Set-SummaryRow $summaryPath ([pscustomobject][ordered]@{
        model_id = $modelId
        reasoning = $reasoning
        terminal_condition = $terminal
        overall_pass = [bool]$result.passed
        completed_tasks = $result.completedTaskCount
        stopped_after_task = $result.stoppedAfterTask
        task1_pass = Get-TaskPass $result 1
        task2_pass = Get-TaskPass $result 2
        task3_pass = Get-TaskPass $result 3
        final_changed_files = (@($result.changedFilesFromInitial) -join ';')
        final_created_files = (@($result.createdFilesFromInitial) -join ';')
        final_deleted_files = (@($result.deletedFilesFromInitial) -join ';')
        exit_code = $runnerExit
      })

      Write-Host ("  Worker pipeline: pass={0}; completed={1}/3; stoppedAfter={2}" -f $result.passed,$result.completedTaskCount,$result.stoppedAfterTask)
    }

    try {
      $psi = [Diagnostics.ProcessStartInfo]::new()
      $psi.FileName = $ollama
      $psi.Arguments = 'stop "' + $modelId + '"'
      $psi.UseShellExecute = $false
      $psi.CreateNoWindow = $true
      $psi.RedirectStandardOutput = $true
      $psi.RedirectStandardError = $true
      $proc = [Diagnostics.Process]::new()
      $proc.StartInfo = $psi
      [void]$proc.Start()
      [void]$proc.StandardOutput.ReadToEnd()
      [void]$proc.StandardError.ReadToEnd()
      $proc.WaitForExit()
    } catch {
      Write-Warning ("Unable to unload " + $modelId + "; continuing batch.")
    }
  }
}
finally {
  [IO.File]::WriteAllBytes($settingsFile,$settingsBackup)
  try { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}

Write-Host ''
Write-Host "Worker Intent 04 batch complete: $OutputRoot"
Write-Host "Summary: $summaryPath"
