param(
  [string]$GovernorRepo = (Join-Path (Split-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path -Parent) 'governor'),
  [string]$CandidatesFile = (Join-Path $PSScriptRoot 'planner\candidates.csv'),
  [string]$OutputRoot = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\role-qualification-v1\governor-screen-v1'),
  [int]$WallSeconds = 600,
  [switch]$Resume
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$singleRunner = Join-Path $PSScriptRoot 'run-role-benchmark-single.ps1'
$extractor = Join-Path $PSScriptRoot 'dsh\extract-planner-batch-result.mjs'
$rolePrompt = Join-Path $PSScriptRoot 'governor\ROLE_PROMPT.txt'
$governorRoot = [IO.Path]::GetFullPath($GovernorRepo)
$law = Join-Path $governorRoot 'docs\LAW.md'
$state = Join-Path $governorRoot 'docs\STATE.md'
$generalIntent = Join-Path $governorRoot 'docs\GENERAL_INTENT.md'
$projectIntent = Join-Path $PSScriptRoot 'governor\reference\PROJECT_INTENT.md'
$settingsFile = Join-Path $env:USERPROFILE '.dsh\settings.yaml'
$utf8 = [Text.UTF8Encoding]::new($false)
$nl = [Environment]::NewLine

$packets = @(
  [pscustomobject]@{
    id = 'packet-a-simple'
    intent = (Join-Path $PSScriptRoot 'planner\intent-03-config-default.md')
    plan = (Join-Path $PSScriptRoot 'governor\plans\plan-a-simple.md')
  },
  [pscustomobject]@{
    id = 'packet-b-medium'
    intent = (Join-Path $PSScriptRoot 'planner\intent-04-batch-export.md')
    plan = (Join-Path $PSScriptRoot 'governor\plans\plan-b-medium.md')
  },
  [pscustomobject]@{
    id = 'packet-c-hard'
    intent = (Join-Path $PSScriptRoot 'planner\intent-05-job-cancellation.md')
    plan = (Join-Path $PSScriptRoot 'governor\plans\plan-c-hard.md')
  },
  [pscustomobject]@{
    id = 'packet-d-contextual-storage'
    intent = (Join-Path $PSScriptRoot 'planner\intent-06-contextual-storage-backend.md')
    plan = (Join-Path $PSScriptRoot 'governor\plans\plan-d-contextual-storage.md')
  }
)

foreach ($required in @($CandidatesFile,$singleRunner,$extractor,$rolePrompt,$law,$state,$generalIntent,$projectIntent,$settingsFile)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}
foreach ($packet in $packets) {
  foreach ($required in @($packet.intent,$packet.plan)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing Governor packet input: $required" }
  }
}
if ($WallSeconds -lt 1) { throw 'WallSeconds must be at least 1.' }

function Read-Utf8([string]$Path) {
  return [IO.File]::ReadAllText($Path, $utf8)
}

function Write-Utf8([string]$Path, [string]$Text) {
  [IO.File]::WriteAllBytes($Path, $utf8.GetBytes($Text))
}

function Yaml-Quote([string]$Text) {
  return "'" + $Text.Replace("'","''") + "'"
}

function Parse-Bool([string]$Value, [string]$Field, [string]$Model) {
  $normalized = ''
  if ($null -ne $Value) { $normalized = $Value.Trim().ToLowerInvariant() }
  switch ($normalized) {
    'true' { return $true }
    'false' { return $false }
    default { throw "Candidate $Model has invalid $Field '$Value'. Expected true or false." }
  }
}

function Get-AdvertisedContext([string]$ModelId) {
  try {
    $body = @{ model = $ModelId } | ConvertTo-Json -Compress
    $show = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11434/api/show' -ContentType 'application/json' -Body $body -TimeoutSec 10
    $values = @()
    if ($show.model_info) {
      foreach ($prop in $show.model_info.PSObject.Properties) {
        if ($prop.Name -match 'context_length$') {
          $number = 0L
          if ([int64]::TryParse([string]$prop.Value, [ref]$number)) { $values += $number }
        }
      }
    }
    if ($values.Count -gt 0) { return ($values | Measure-Object -Maximum).Maximum }
  } catch {}
  return $null
}

function Get-ExistingSummaryModels([string]$SummaryPath) {
  if (-not (Test-Path -LiteralPath $SummaryPath)) { return @() }
  try { return @((Import-Csv -LiteralPath $SummaryPath).model_id) } catch { return @() }
}

function Set-SummaryRow([string]$SummaryPath, $Row) {
  $rows = @()
  if (Test-Path -LiteralPath $SummaryPath) {
    try { $rows = @(Import-Csv -LiteralPath $SummaryPath | Where-Object { $_.model_id -ne $Row.model_id }) }
    catch { $rows = @() }
  }
  $rows += $Row
  $rows | Export-Csv -LiteralPath $SummaryPath -NoTypeInformation -Encoding UTF8
}

function New-CandidatePatch($Candidate, [string]$PatchPath, [bool]$ThinkingCapable) {
  $model = Yaml-Quote $Candidate.model_id
  $display = Yaml-Quote $Candidate.model_id
  $reason = [string]$Candidate.reasoning_effort
  $agentReason = ''
  $modelReason = ''
  if ($reason.Trim().Length -gt 0) {
    $quotedReason = Yaml-Quote $reason.Trim()
    $agentReason = $nl + "    reasoningEffort: $quotedReason"
    $modelReason = $nl + "            reasoningEffort: $quotedReason"
  }
  $thinking = if ($ThinkingCapable) { 'true' } else { 'false' }

  $yaml = @"
- id: agent-default-model
  config:
    provider: role-benchmark-native
    model: $model$agentReason

- id: llm-ollama
  config:
    providers:
      role-benchmark-native:
        displayName: Role Benchmark Native Ollama
        api: ollama-chat
        baseURL: http://127.0.0.1:11434
        keepAlive: 30m
        models:
          - id: $model
            name: $display
            contextWindow: $($Candidate.context_window)
            maxTokens: $($Candidate.max_tokens)
            thinkingCapable: $thinking$modelReason

- id: llm-deepseek
  disabled: true

- id: llm-pi-ai
  disabled: true
"@
  Write-Utf8 $PatchPath $yaml
}

function Write-CandidateSettings($Candidate, [bool]$ThinkingCapable) {
  $model = Yaml-Quote $Candidate.model_id
  $display = Yaml-Quote $Candidate.model_id
  $reason = [string]$Candidate.reasoning_effort
  $modelReason = ''
  if ($reason.Trim().Length -gt 0) {
    $modelReason = $nl + "          reasoningEffort: " + (Yaml-Quote $reason.Trim())
  }
  $thinking = if ($ThinkingCapable) { 'true' } else { 'false' }

  $yaml = @"
llm-ollama:
  providers:
    role-benchmark-native:
      displayName: Role Benchmark Native Ollama
      api: ollama-chat
      baseURL: http://127.0.0.1:11434
      keepAlive: 30m
      models:
        - id: $model
          name: $display
          contextWindow: $($Candidate.context_window)
          maxTokens: $($Candidate.max_tokens)
          thinkingCapable: $thinking$modelReason
"@
  Write-Utf8 $settingsFile $yaml
}

function Build-Packet([string]$IntentPath, [string]$PlanPath, [string]$OutPath) {
  $text = @"
# Governor Review Packet

## Qualification Condition

This is an isolated qualification simulation. You are reviewing the supplied plan only. You are not executing a live governed action and are not being asked to establish or modify a protected role-to-model assignment.

The unfinished Owner identity and protected role-to-model assignment entries in State are outside this benchmark condition. Do not use those unfinished entries as a reason to reject or leave unresolved an otherwise reviewable plan unless the proposed plan itself requires an Owner-only action or changes a protected assignment.

All other supplied Law, State, General Intent, Project Intent, and task constraints apply normally.

## Original Project Intent

$(Read-Utf8 $IntentPath)

## Proposed Plan

$(Read-Utf8 $PlanPath)

## Law

$(Read-Utf8 $law)

## State

$(Read-Utf8 $state)

## General Intent

$(Read-Utf8 $generalIntent)

## Project Intent

$(Read-Utf8 $projectIntent)
"@
  Write-Utf8 $OutPath $text
}

$candidates = @(Import-Csv -LiteralPath $CandidatesFile)
if ($candidates.Count -lt 1) { throw "No candidates found in $CandidatesFile" }

try {
  $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
  throw 'Ollama is not reachable at http://127.0.0.1:11434. Start Ollama before running the Governor batch.'
}

$installed = @{}
foreach ($m in @($tags.models)) { $installed[[string]$m.name] = $m }

$settingsBackup = [IO.File]::ReadAllBytes($settingsFile)
$scratch = Join-Path $env:TEMP ('local-model-bench-governor-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

try {
  foreach ($packet in $packets) {
    New-Item -ItemType Directory -Path (Join-Path $OutputRoot $packet.id) -Force | Out-Null
  }

  foreach ($candidate in $candidates) {
    $modelId = [string]$candidate.model_id
    $fileName = [string]$candidate.file_name
    $contextWindow = [int]$candidate.context_window
    $thinkingCapable = Parse-Bool ([string]$candidate.thinking_capable) 'thinking_capable' $modelId
    $reasoning = ([string]$candidate.reasoning_effort).Trim()

    if (-not $installed.ContainsKey($modelId)) {
      Write-Warning ("Skipping " + $modelId + ": not installed in Ollama.")
      continue
    }

    $advertisedContext = Get-AdvertisedContext $modelId
    $modelSize = $installed[$modelId].size
    Write-CandidateSettings $candidate $thinkingCapable

    $patchPath = Join-Path $scratch ($fileName + '.patch.yml')
    New-CandidatePatch $candidate $patchPath $thinkingCapable

    Write-Host ''
    Write-Host ('=' * 72)
    Write-Host "Governor candidate: $modelId"
    Write-Host "Context: configured=$contextWindow advertised=$advertisedContext"
    if ($reasoning) { Write-Host "Reasoning: $reasoning" } else { Write-Host 'Reasoning: default' }
    Write-Host ('=' * 72)

    foreach ($packet in $packets) {
      $packetDir = Join-Path $OutputRoot $packet.id
      $summaryPath = Join-Path $packetDir 'summary.csv'
      $markdownPath = Join-Path $packetDir ($fileName + '.md')

      if ($Resume) {
        $existingModels = Get-ExistingSummaryModels $summaryPath
        if ((Test-Path -LiteralPath $markdownPath) -and ($existingModels -contains $modelId)) {
          Write-Host "Skipping completed: $modelId / $($packet.id)"
          continue
        }
      } elseif (Test-Path -LiteralPath $markdownPath) {
        throw "Result already exists: $markdownPath. Use -Resume to continue a partial batch."
      }

      $packagePath = Join-Path $scratch ($packet.id + '-' + $fileName + '-package.md')
      Build-Packet $packet.intent $packet.plan $packagePath

      $runDir = Join-Path $scratch ($fileName + '-' + $packet.id + '-' + [Guid]::NewGuid().ToString('N'))
      $consoleLog = $runDir + '.console.txt'
      $extractJson = $runDir + '.extract.json'

      Write-Host "Running $($packet.id)..."
      & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $singleRunner -CandidatePatch $patchPath -RuntimeKind ollama -ModelId $modelId -ExpectedContextWindow $contextWindow -RolePrompt $rolePrompt -PackageFile $packagePath -OutputDir $runDir -WallSeconds $WallSeconds *> $consoleLog
      $exitCode = $LASTEXITCODE

      $runJson = Join-Path $runDir 'run.json'
      $extract = $null
      if (Test-Path -LiteralPath $runJson) {
        & node.exe $extractor $runJson $extractJson
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $extractJson)) {
          $extract = Get-Content -LiteralPath $extractJson -Raw | ConvertFrom-Json
        }
      }

      if ($extract) { $terminal = [string]$extract.terminalCondition }
      elseif ($exitCode -eq 124) { $terminal = 'wall_clock' }
      else { $terminal = 'runtime_error' }

      $wall = if ($extract) { $extract.wallClockSeconds } else { $null }
      $effectiveContext = if ($extract) { $extract.effectiveContextWindow } else { $null }
      $inputTokens = if ($extract) { $extract.inputTokens } else { $null }
      $outputTokens = if ($extract) { $extract.outputTokens } else { $null }
      $totalTokens = if ($extract) { $extract.totalTokens } else { $null }
      $finalOutput = if ($extract -and $extract.finalOutput) { [string]$extract.finalOutput } else { '' }
      $rate = $null
      if ($null -ne $outputTokens -and $null -ne $wall -and [double]$wall -gt 0) {
        $rate = [math]::Round(([double]$outputTokens / [double]$wall), 3)
      }

      $md = "# $modelId" + $nl + $nl
      if ($finalOutput.Length -gt 0) { $md += $finalOutput.TrimEnd() + $nl }
      else { $md += "_No final Governor output captured. See summary.csv for terminal condition._" + $nl }
      Write-Utf8 $markdownPath $md

      if ($reasoning) { $reasoningSummary = $reasoning } else { $reasoningSummary = 'default' }
      Set-SummaryRow $summaryPath ([pscustomobject][ordered]@{
        model_id = $modelId
        runtime = 'ollama-native'
        reasoning = $reasoningSummary
        advertised_context = $(if ($null -ne $advertisedContext) { $advertisedContext } else { '' })
        configured_context = $contextWindow
        effective_context = $(if ($null -ne $effectiveContext) { $effectiveContext } else { '' })
        wall_seconds = $(if ($null -ne $wall) { $wall } else { '' })
        input_tokens = $(if ($null -ne $inputTokens) { $inputTokens } else { '' })
        output_tokens = $(if ($null -ne $outputTokens) { $outputTokens } else { '' })
        total_tokens = $(if ($null -ne $totalTokens) { $totalTokens } else { '' })
        overall_output_tok_per_sec = $(if ($null -ne $rate) { $rate } else { '' })
        model_size_bytes = $(if ($null -ne $modelSize) { $modelSize } else { '' })
        terminal_condition = $terminal
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
      })

      Write-Host ("  {0}: {1}; {2}s; in={3} out={4}" -f $packet.id,$terminal,$wall,$inputTokens,$outputTokens)

      try { Remove-Item -LiteralPath $runDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
      try { Remove-Item -LiteralPath $consoleLog -Force -ErrorAction SilentlyContinue } catch {}
      try { Remove-Item -LiteralPath $extractJson -Force -ErrorAction SilentlyContinue } catch {}
      try { Remove-Item -LiteralPath $packagePath -Force -ErrorAction SilentlyContinue } catch {}
    }
  }
}
finally {
  [IO.File]::WriteAllBytes($settingsFile, $settingsBackup)
  try { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}

Write-Host ''
Write-Host "Governor batch complete: $OutputRoot"
