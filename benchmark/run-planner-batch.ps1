param(
  [string]$CandidatesFile = (Join-Path $PSScriptRoot 'planner\candidates.csv'),
  [string]$OutputRoot = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\role-qualification-v1\planner-screen-v1'),
  [int]$WallSeconds = 600,
  [switch]$Resume
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$singleRunner = Join-Path $PSScriptRoot 'run-role-benchmark-single.ps1'
$extractor = Join-Path $PSScriptRoot 'dsh\extract-planner-batch-result.mjs'
$rolePrompt = Join-Path $PSScriptRoot 'planner\ROLE_PROMPT.txt'
$settingsFile = Join-Path $env:USERPROFILE '.dsh\settings.yaml'
$utf8 = [Text.UTF8Encoding]::new($false)
$nl = [Environment]::NewLine

$intents = @(
  [pscustomobject]@{
    id = 'intent-01'
    path = (Join-Path $PSScriptRoot 'planner\intent-01-cli-time-filter.md')
  },
  [pscustomobject]@{
    id = 'intent-02'
    path = (Join-Path $PSScriptRoot 'planner\intent-02-webhook-retry-policy.md')
  }
)

foreach ($required in @($CandidatesFile,$singleRunner,$extractor,$rolePrompt,$settingsFile)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}
foreach ($intent in $intents) {
  if (-not (Test-Path -LiteralPath $intent.path)) { throw "Missing frozen intent: $($intent.path)" }
}
if ($WallSeconds -lt 1) { throw 'WallSeconds must be at least 1.' }

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

function Add-SummaryRow([string]$SummaryPath, $Row) {
  if (Test-Path -LiteralPath $SummaryPath) {
    $Row | Export-Csv -LiteralPath $SummaryPath -NoTypeInformation -Append -Encoding UTF8
  } else {
    $Row | Export-Csv -LiteralPath $SummaryPath -NoTypeInformation -Encoding UTF8
  }
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

$candidates = @(Import-Csv -LiteralPath $CandidatesFile)
if ($candidates.Count -lt 1) { throw "No candidates found in $CandidatesFile" }

$seenFiles = @{}
foreach ($candidate in $candidates) {
  foreach ($field in @('model_id','file_name','context_window','max_tokens','thinking_capable')) {
    if ([string]::IsNullOrWhiteSpace([string]$candidate.$field)) {
      throw "Candidate row is missing required field '$field'."
    }
  }
  if ($candidate.file_name -match '[<>:"/\\|?*]') {
    throw "Candidate $($candidate.model_id) has invalid Windows file_name '$($candidate.file_name)'."
  }
  if ($seenFiles.ContainsKey($candidate.file_name)) {
    throw "Duplicate candidate file_name '$($candidate.file_name)'."
  }
  $seenFiles[$candidate.file_name] = $true
  [void][int]::Parse($candidate.context_window)
  [void][int]::Parse($candidate.max_tokens)
}

try {
  $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
  throw 'Ollama is not reachable at http://127.0.0.1:11434. Start Ollama before running the Planner batch.'
}

$installed = @{}
foreach ($m in @($tags.models)) { $installed[[string]$m.name] = $m }

$settingsBackup = [IO.File]::ReadAllBytes($settingsFile)
$batchScratch = Join-Path $env:TEMP ('local-model-bench-planner-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $batchScratch -Force | Out-Null
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

try {
  foreach ($intent in $intents) {
    $intentDir = Join-Path $OutputRoot $intent.id
    New-Item -ItemType Directory -Path $intentDir -Force | Out-Null
  }

  foreach ($candidate in $candidates) {
    $modelId = [string]$candidate.model_id
    $fileName = [string]$candidate.file_name
    $contextWindow = [int]$candidate.context_window
    $maxTokens = [int]$candidate.max_tokens
    $thinkingCapable = Parse-Bool ([string]$candidate.thinking_capable) 'thinking_capable' $modelId
    $reasoning = ([string]$candidate.reasoning_effort).Trim()

    if (-not $installed.ContainsKey($modelId)) {
      Write-Warning "Skipping $modelId: not installed in Ollama."
      foreach ($intent in $intents) {
        $summaryPath = Join-Path (Join-Path $OutputRoot $intent.id) 'summary.csv'
        Add-SummaryRow $summaryPath ([pscustomobject][ordered]@{
          model_id = $modelId
          runtime = 'ollama-native'
          reasoning = $reasoning
          advertised_context = ''
          configured_context = $contextWindow
          effective_context = ''
          wall_seconds = ''
          input_tokens = ''
          output_tokens = ''
          total_tokens = ''
          overall_output_tok_per_sec = ''
          model_size_bytes = ''
          terminal_condition = 'not_installed'
          timestamp_utc = [DateTime]::UtcNow.ToString('o')
        })
      }
      continue
    }

    $advertisedContext = Get-AdvertisedContext $modelId
    $modelSize = $installed[$modelId].size

    Write-CandidateSettings $candidate $thinkingCapable
    $patchPath = Join-Path $batchScratch ($fileName + '.patch.yml')
    New-CandidatePatch $candidate $patchPath $thinkingCapable

    Write-Host ''
    Write-Host ('=' * 72)
    Write-Host "Planner candidate: $modelId"
    Write-Host "Context: configured=$contextWindow advertised=$advertisedContext"
    if ($reasoning) { Write-Host "Reasoning: $reasoning" } else { Write-Host 'Reasoning: default' }
    Write-Host ('=' * 72)

    foreach ($intent in $intents) {
      $intentDir = Join-Path $OutputRoot $intent.id
      $summaryPath = Join-Path $intentDir 'summary.csv'
      $markdownPath = Join-Path $intentDir ($fileName + '.md')

      if ($Resume) {
        $existingModels = Get-ExistingSummaryModels $summaryPath
        if ((Test-Path -LiteralPath $markdownPath) -and ($existingModels -contains $modelId)) {
          Write-Host "Skipping completed: $modelId / $($intent.id)"
          continue
        }
      } elseif (Test-Path -LiteralPath $markdownPath) {
        throw "Result already exists: $markdownPath. Use -Resume to continue a partial batch."
      }

      $scratchRun = Join-Path $batchScratch ($fileName + '-' + $intent.id + '-' + [Guid]::NewGuid().ToString('N'))
      $consoleLog = $scratchRun + '.console.txt'
      $extractJson = $scratchRun + '.extract.json'

      Write-Host "Running $($intent.id)..."
      & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $singleRunner -CandidatePatch $patchPath -RuntimeKind ollama -ModelId $modelId -ExpectedContextWindow $contextWindow -RolePrompt $rolePrompt -PackageFile $intent.path -OutputDir $scratchRun -WallSeconds $WallSeconds *> $consoleLog
      $exitCode = $LASTEXITCODE

      $runJson = Join-Path $scratchRun 'run.json'
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

      $overallRate = $null
      if ($null -ne $outputTokens -and $null -ne $wall -and [double]$wall -gt 0) {
        $overallRate = [math]::Round(([double]$outputTokens / [double]$wall), 3)
      }

      $md = "# $modelId" + $nl + $nl
      if ($finalOutput.Length -gt 0) {
        $md += $finalOutput.TrimEnd() + $nl
      } else {
        $md += "_No final model output captured. See summary.csv for terminal condition._" + $nl
      }
      Write-Utf8 $markdownPath $md

      if ($reasoning) { $reasoningSummary = $reasoning } else { $reasoningSummary = 'default' }
      Add-SummaryRow $summaryPath ([pscustomobject][ordered]@{
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
        overall_output_tok_per_sec = $(if ($null -ne $overallRate) { $overallRate } else { '' })
        model_size_bytes = $(if ($null -ne $modelSize) { $modelSize } else { '' })
        terminal_condition = $terminal
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
      })

      Write-Host ("  {0}: {1}; {2}s; in={3} out={4}" -f $intent.id,$terminal,$wall,$inputTokens,$outputTokens)

      try { Remove-Item -LiteralPath $scratchRun -Recurse -Force -ErrorAction SilentlyContinue } catch {}
      try { Remove-Item -LiteralPath $consoleLog -Force -ErrorAction SilentlyContinue } catch {}
      try { Remove-Item -LiteralPath $extractJson -Force -ErrorAction SilentlyContinue } catch {}
    }
  }
}
finally {
  [IO.File]::WriteAllBytes($settingsFile, $settingsBackup)
  try { Remove-Item -LiteralPath $batchScratch -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}

Write-Host ''
Write-Host "Planner batch complete: $OutputRoot"
Write-Host 'Each intent directory contains only model .md outputs and summary.csv.'
