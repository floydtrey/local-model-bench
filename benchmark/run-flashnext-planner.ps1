param(
  [string]$OutputRoot = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'local-state\role-qualification-v1\planner-screen-v1'),
  [int]$WallSeconds = 600
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$settingsFile = Join-Path $dshHome 'settings.yaml'
$basePatch = Join-Path $repo 'benchmark\dsh\role-qualification-v1.patch.yml'
$candidatePatch = Join-Path $repo 'benchmark\dsh\flashnext-c01.patch.yml'
$dshRunner = Join-Path $repo 'benchmark\dsh\run-single-dsh.ps1'
$observer = Join-Path $repo 'benchmark\dsh\passive-observer.mjs'
$extractor = Join-Path $repo 'benchmark\dsh\extract-planner-batch-result.mjs'
$rolePrompt = Join-Path $repo 'benchmark\planner\ROLE_PROMPT.txt'
$utf8 = [Text.UTF8Encoding]::new($false)
$nl = [Environment]::NewLine
$modelId = 'C01'
$fileName = 'qwen3.8-flash-next'
$contextWindow = 262144

$intents = @(
  [pscustomobject]@{ id='intent-01'; path=(Join-Path $repo 'benchmark\planner\intent-01-cli-time-filter.md') },
  [pscustomobject]@{ id='intent-02'; path=(Join-Path $repo 'benchmark\planner\intent-02-webhook-retry-policy.md') }
)

foreach ($required in @($dsh,$settingsFile,$basePatch,$candidatePatch,$dshRunner,$observer,$extractor,$rolePrompt)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required file: $required" }
}
foreach ($intent in $intents) {
  if (-not (Test-Path -LiteralPath $intent.path)) { throw "Missing frozen intent: $($intent.path)" }
}

function Write-Utf8([string]$Path, [string]$Text) {
  [IO.File]::WriteAllBytes($Path, $utf8.GetBytes($Text))
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

try {
  $models = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/models' -TimeoutSec 5
} catch {
  throw 'Flash-Next llama.cpp server is not reachable at http://127.0.0.1:8080/v1. Start the verified C01 server first.'
}

$servedIds = @()
if ($models.data) { $servedIds += @($models.data | ForEach-Object { $_.id }) }
if ($models.models) {
  $servedIds += @($models.models | ForEach-Object {
    if ($_.id) { $_.id }
    elseif ($_.name) { $_.name }
    elseif ($_.model) { $_.model }
  })
}
if ($servedIds -notcontains 'C01') {
  throw "Flash-Next endpoint is reachable but does not report model alias C01. Reported: $($servedIds -join ', ')"
}

$settingsBackup = [IO.File]::ReadAllBytes($settingsFile)
$scratchRoot = Join-Path $env:TEMP ('local-model-bench-flashnext-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratchRoot -Force | Out-Null
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

try {
  $env:FLASHNEXT_LOCAL_KEY = 'local'
  $env:DSH_HOME = $dshHome
  $env:DSH_TELEMETRY_DISABLED = '1'

  $settings = @"
llm-pi-ai:
  providers:
    flashnext-local:
      displayName: Flash-Next C01
      api: openai-completions
      baseURL: http://127.0.0.1:8080/v1
      apiKeyEnv: FLASHNEXT_LOCAL_KEY
      models:
        - id: C01
          name: Qwen3.8 Flash-Next UD-IQ3_XXS
          contextWindow: 262144
          input:
            - text
"@
  Write-Utf8 $settingsFile $settings

  $dump = (& $dsh --profile headless --dump-config 2>&1 | Out-String)
  if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the DSH headless profile.' }
  if ($dump -notmatch 'llm-pi-ai') { throw 'DSH headless profile does not contain llm-pi-ai.' }

  foreach ($intent in $intents) {
    $intentDir = Join-Path $OutputRoot $intent.id
    New-Item -ItemType Directory -Path $intentDir -Force | Out-Null
    $markdownPath = Join-Path $intentDir ($fileName + '.md')
    $summaryPath = Join-Path $intentDir 'summary.csv'

    if (Test-Path -LiteralPath $markdownPath) {
      throw "Flash-Next result already exists: $markdownPath"
    }

    $runDir = Join-Path $scratchRoot ($intent.id + '-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
    $obsState = Join-Path $runDir 'observer-state.json'
    $obsJson = Join-Path $runDir 'observations.json'
    $runJson = Join-Path $runDir 'run.json'
    $extractJson = Join-Path $runDir 'extract.json'

    & node.exe $observer before $obsState $dshHome
    if ($LASTEXITCODE -ne 0) { throw "Failed to snapshot DSH state before $($intent.id)." }

    $started = Get-Date
    Write-Host ''
    Write-Host "Flash-Next C01 / $($intent.id)"
    Write-Host 'Runtime: llama.cpp special @ 127.0.0.1:8080'
    Write-Host 'Context: 262144'

    $args = @(
      '-NoProfile','-ExecutionPolicy','Bypass','-File',$dshRunner,
      '-DshPath',$dsh,
      '-BasePatch',$basePatch,
      '-CandidatePatch',$candidatePatch,
      '-RolePrompt',$rolePrompt,
      '-PackageFile',$intent.path,
      '-WallSeconds',[string]$WallSeconds,
      '-RunJson',$runJson,
      '-RunStartedAt',$started
    )
    & powershell.exe @args
    $exitCode = $LASTEXITCODE

    & node.exe $observer after $obsState $dshHome $obsJson $exitCode
    if ($LASTEXITCODE -ne 0) { throw "Passive observation failed for $($intent.id)." }

    if (Test-Path -LiteralPath $runJson) {
      $record = Get-Content -LiteralPath $runJson -Raw | ConvertFrom-Json
      $obs = Get-Content -LiteralPath $obsJson -Raw | ConvertFrom-Json
      $record | Add-Member -NotePropertyName runtimeKind -NotePropertyValue 'llama.cpp-special' -Force
      $record | Add-Member -NotePropertyName modelId -NotePropertyValue $modelId -Force
      $record | Add-Member -NotePropertyName expectedContextWindow -NotePropertyValue $contextWindow -Force
      $record | Add-Member -NotePropertyName effectiveContextWindow -NotePropertyValue $contextWindow -Force
      $record | Add-Member -NotePropertyName nativeSessionEvidence -NotePropertyValue $obs.evidence.nativeSession -Force
      Write-Utf8 $runJson ($record | ConvertTo-Json -Depth 8)
    }

    & node.exe $extractor $runJson $extractJson
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $extractJson)) {
      throw "Could not extract Flash-Next result for $($intent.id)."
    }

    $extract = Get-Content -LiteralPath $extractJson -Raw | ConvertFrom-Json
    $finalOutput = [string]$extract.finalOutput
    $md = "# qwen3.8-flash-next" + $nl + $nl
    if ($finalOutput.Length -gt 0) { $md += $finalOutput.TrimEnd() + $nl }
    else { $md += "_No final model output captured. See summary.csv for terminal condition._" + $nl }
    Write-Utf8 $markdownPath $md

    $wall = $extract.wallClockSeconds
    $inputTokens = $extract.inputTokens
    $outputTokens = $extract.outputTokens
    $totalTokens = $extract.totalTokens
    $rate = $null
    if ($null -ne $outputTokens -and $null -ne $wall -and [double]$wall -gt 0) {
      $rate = [math]::Round(([double]$outputTokens / [double]$wall), 3)
    }

    Set-SummaryRow $summaryPath ([pscustomobject][ordered]@{
      model_id = 'qwen3.8-flash-next'
      runtime = 'llama.cpp-special'
      reasoning = 'server-auto'
      advertised_context = ''
      configured_context = 262144
      effective_context = 262144
      wall_seconds = $(if ($null -ne $wall) { $wall } else { '' })
      input_tokens = $(if ($null -ne $inputTokens) { $inputTokens } else { '' })
      output_tokens = $(if ($null -ne $outputTokens) { $outputTokens } else { '' })
      total_tokens = $(if ($null -ne $totalTokens) { $totalTokens } else { '' })
      overall_output_tok_per_sec = $(if ($null -ne $rate) { $rate } else { '' })
      model_size_bytes = 81961823936
      terminal_condition = [string]$extract.terminalCondition
      timestamp_utc = [DateTime]::UtcNow.ToString('o')
    })

    Write-Host ("  {0}: {1}; {2}s; in={3} out={4}" -f $intent.id,$extract.terminalCondition,$wall,$inputTokens,$outputTokens)
    try { Remove-Item -LiteralPath $runDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
  }
}
finally {
  [IO.File]::WriteAllBytes($settingsFile, $settingsBackup)
  Remove-Item Env:FLASHNEXT_LOCAL_KEY -ErrorAction SilentlyContinue
  try { Remove-Item -LiteralPath $scratchRoot -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}
