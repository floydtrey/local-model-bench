param(
  [string]$CandidatesFile = (Join-Path $PSScriptRoot 'worker\candidates.csv'),
  [string]$OutputRoot = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\worker-qualification-v1\test-01-batch-v1'),
  [int]$WallSecondsPerTurn = 300,
  [switch]$Resume
)

$ErrorActionPreference = 'Stop'
$singleRunner = Join-Path $PSScriptRoot 'run-worker-qualification-test01.ps1'
$settingsFile = Join-Path $env:USERPROFILE '.dsh\settings.yaml'
$utf8 = [Text.UTF8Encoding]::new($false)
$nl = [Environment]::NewLine

foreach ($required in @($CandidatesFile,$singleRunner,$settingsFile)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}

function Write-Utf8([string]$Path,[string]$Text) { [IO.File]::WriteAllBytes($Path,$utf8.GetBytes($Text)) }
function Yaml-Quote([string]$Text) { return "'" + $Text.Replace("'","''") + "'" }
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
    try { $rows = @(Import-Csv -LiteralPath $Path | Where-Object { $_.model_id -ne $Row.model_id }) } catch { $rows = @() }
  }
  $rows += $Row
  $rows | Export-Csv -LiteralPath $Path -NoTypeInformation -Encoding UTF8
}

$candidates = @(Import-Csv -LiteralPath $CandidatesFile)
if ($candidates.Count -lt 1) { throw 'No Worker candidates found.' }

try { $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 } catch { throw 'Ollama is not reachable.' }
$installed = @{}
foreach ($m in @($tags.models)) { $installed[[string]$m.name] = $m }

$settingsBackup = [IO.File]::ReadAllBytes($settingsFile)
$scratch = Join-Path $env:TEMP ('local-model-bench-worker-' + [Guid]::NewGuid().ToString('N'))
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

    if ($Resume -and (Test-Path -LiteralPath (Join-Path $modelOutput 'result.json'))) { Write-Host "Skipping completed: $modelId"; continue }
    if ((Test-Path -LiteralPath $modelOutput) -and -not $Resume) { throw "Result directory already exists: $modelOutput" }

    if (-not $installed.ContainsKey($modelId)) {
      Write-Warning "Skipping ${modelId}: not installed."
      Set-SummaryRow $summaryPath ([pscustomobject][ordered]@{model_id=$modelId;reasoning=$reasoning;terminal_condition='not_installed';harness_pass='';dispatch_completed='';scope_pass='';behavior_pass='';regression_tests_pass='';handoff_present='';input_tokens='';output_tokens='';wall_seconds='';changed_files='';created_files='';deleted_files=''})
      continue
    }

    Write-CandidateSettings $candidate $thinkingCapable
    $patchPath = Join-Path $scratch ($fileName + '.patch.yml')
    New-CandidatePatch $candidate $patchPath $thinkingCapable

    Write-Host ''
    Write-Host ('=' * 72)
    Write-Host "Worker candidate: $modelId"
    Write-Host "Reasoning: $reasoning"
    Write-Host ('=' * 72)

    $args = @{CandidatePatch=$patchPath;ModelId=$modelId;OutputDir=$modelOutput;WallSecondsPerTurn=$WallSecondsPerTurn}
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $singleRunner @args
    $runnerExit = $LASTEXITCODE

    $resultPath = Join-Path $modelOutput 'result.json'
    if (-not (Test-Path -LiteralPath $resultPath)) {
      Set-SummaryRow $summaryPath ([pscustomobject][ordered]@{model_id=$modelId;reasoning=$reasoning;terminal_condition='harness_error';harness_pass='';dispatch_completed='';scope_pass='';behavior_pass='';regression_tests_pass='';handoff_present='';input_tokens='';output_tokens='';wall_seconds='';changed_files='';created_files='';deleted_files=''})
      continue
    }

    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    $scopePass = ($result.checks.onlyAuthorizedFileChanged -eq $true -and $result.checks.noUnauthorizedChangedFiles -eq $true -and $result.checks.noFilesCreated -eq $true -and $result.checks.noFilesDeleted -eq $true)
    $terminal = if ($runnerExit -eq 0) { 'completed' } else { 'model_fail' }
    $dispatch = $result.dispatchTurn
    Set-SummaryRow $summaryPath ([pscustomobject][ordered]@{
      model_id=$modelId;reasoning=$reasoning;terminal_condition=$terminal;harness_pass=[bool]$result.passed;dispatch_completed=[bool]$result.checks.dispatchTurnCompleted;scope_pass=[bool]$scopePass;behavior_pass=[bool]$result.checks.configBehaviorPass;regression_tests_pass=[bool]$result.checks.existingTestsPass;handoff_present=[bool]$result.checks.handoffPresent;input_tokens=$dispatch.inputTokens;output_tokens=$dispatch.outputTokens;wall_seconds=$dispatch.wallSeconds;changed_files=(@($result.changedFiles)-join ';');created_files=(@($result.createdFiles)-join ';');deleted_files=(@($result.deletedFiles)-join ';')
    })
    Write-Host ("  Result: pass={0} scope={1} behavior={2} tests={3} handoff={4}" -f $result.passed,$scopePass,$result.checks.configBehaviorPass,$result.checks.existingTestsPass,$result.checks.handoffPresent)
  }
} finally {
  [IO.File]::WriteAllBytes($settingsFile,$settingsBackup)
  try { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}

Write-Host ''
Write-Host "Worker Test 01 batch complete: $OutputRoot"
Write-Host "Summary: $summaryPath"
