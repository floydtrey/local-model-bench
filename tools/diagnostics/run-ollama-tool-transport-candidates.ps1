param(
    [Parameter(Mandatory = $true)]
    [string[]]$Models,

    [string]$BaseUrl = "http://127.0.0.1:11434",

    [string]$OutputRoot = "local-state/tool-transport-smoke",

    [int]$NumCtx = 32768,

    [int]$NumPredict = 128
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$SmokeScript = Join-Path $Here "ollama-tool-transport-smoke.ps1"
if (-not (Test-Path -LiteralPath $SmokeScript -PathType Leaf)) {
    throw "Smoke script not found: $SmokeScript"
}

$BatchTimestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$BatchDir = Join-Path $OutputRoot "batch-$BatchTimestamp"
New-Item -ItemType Directory -Path $BatchDir -Force | Out-Null

$Results = @()

foreach ($Model in $Models) {
    Write-Host ""
    Write-Host "=== $Model ===" -ForegroundColor Cyan

    $Before = @(
        Get-ChildItem -Path $OutputRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne (Split-Path -Leaf $BatchDir) } |
            Select-Object -ExpandProperty FullName
    )

    $ExitCode = 0
    try {
        & $SmokeScript `
            -Model $Model `
            -BaseUrl $BaseUrl `
            -OutputRoot $OutputRoot `
            -NumCtx $NumCtx `
            -NumPredict $NumPredict
        $ExitCode = $LASTEXITCODE
    }
    catch {
        $ExitCode = 1
        Write-Warning $_.Exception.Message
    }

    $After = @(
        Get-ChildItem -Path $OutputRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne (Split-Path -Leaf $BatchDir) } |
            Sort-Object LastWriteTimeUtc -Descending
    )

    $NewRun = $After |
        Where-Object { $Before -notcontains $_.FullName } |
        Select-Object -First 1

    if ($null -eq $NewRun) {
        $Results += [pscustomobject]@{
            model = $Model
            status = "no_evidence_directory"
            structured_tool_call_present = $null
            semantic_tool_selection = "unknown"
            argument_correctness = "unknown"
            protocol_parser_compatibility = "unknown"
            wall_time_ms = $null
            run_directory = $null
            exit_code = $ExitCode
        }
        continue
    }

    $SummaryPath = Join-Path $NewRun.FullName "summary.json"
    if (-not (Test-Path -LiteralPath $SummaryPath -PathType Leaf)) {
        $Results += [pscustomobject]@{
            model = $Model
            status = "summary_missing"
            structured_tool_call_present = $null
            semantic_tool_selection = "unknown"
            argument_correctness = "unknown"
            protocol_parser_compatibility = "unknown"
            wall_time_ms = $null
            run_directory = $NewRun.FullName
            exit_code = $ExitCode
        }
        continue
    }

    $Summary = Get-Content -LiteralPath $SummaryPath -Raw | ConvertFrom-Json
    $Results += [pscustomobject]@{
        model = $Model
        status = $Summary.status
        structured_tool_call_present = $Summary.structured_tool_call_present
        semantic_tool_selection = $Summary.semantic_tool_selection
        argument_correctness = $Summary.argument_correctness
        protocol_parser_compatibility = $Summary.protocol_parser_compatibility
        wall_time_ms = $Summary.wall_time_ms
        run_directory = $Summary.run_directory
        exit_code = $ExitCode
    }
}

$JsonPath = Join-Path $BatchDir "comparison.json"
$CsvPath = Join-Path $BatchDir "comparison.csv"

$Results | ConvertTo-Json -Depth 20 | Set-Content -Path $JsonPath -Encoding utf8
$Results | Export-Csv -Path $CsvPath -NoTypeInformation -Encoding utf8

Write-Host ""
Write-Host "=== TRANSPORT COMPARISON ===" -ForegroundColor Green
$Results | Format-Table -AutoSize
Write-Host ""
Write-Host "Comparison JSON: $JsonPath"
Write-Host "Comparison CSV:  $CsvPath"
