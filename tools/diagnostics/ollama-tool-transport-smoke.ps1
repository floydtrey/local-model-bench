param(
    [Parameter(Mandatory = $true)]
    [string]$Model,

    [string]$BaseUrl = "http://127.0.0.1:11434",

    [string]$OutputRoot = "local-state/tool-transport-smoke",

    [int]$NumCtx = 32768,

    [int]$NumPredict = 128
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function ConvertTo-SafeName {
    param([Parameter(Mandatory = $true)][string]$Value)
    return ($Value -replace '[^A-Za-z0-9._-]', '_')
}

$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$SafeModel = ConvertTo-SafeName $Model
$RunDir = Join-Path $OutputRoot "$SafeModel-$Timestamp"
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

$ToolDefinitions = @(
    @{
        type = "function"
        function = @{
            name = "read_file"
            description = "Read one explicitly authorized UTF-8 file by exact relative path."
            parameters = @{
                type = "object"
                additionalProperties = $false
                required = @("path")
                properties = @{
                    path = @{
                        type = "string"
                        minLength = 1
                    }
                }
            }
        }
    },
    @{
        type = "function"
        function = @{
            name = "write_file"
            description = "Atomically write one explicitly authorized UTF-8 file. expected_sha256 is null only for creation and otherwise must match the current file."
            parameters = @{
                type = "object"
                additionalProperties = $false
                required = @("path", "content", "expected_sha256")
                properties = @{
                    path = @{
                        type = "string"
                        minLength = 1
                    }
                    content = @{
                        type = "string"
                    }
                    expected_sha256 = @{
                        anyOf = @(
                            @{ type = "string"; pattern = "^[0-9a-f]{64}$" },
                            @{ type = "null" }
                        )
                    }
                }
            }
        }
    }
)

$RequestObject = @{
    model = $Model
    messages = @(
        @{
            role = "system"
            content = "Use only the supplied tools and only explicitly authorized relative paths. Do not write a file unless the task explicitly requires a file mutation."
        },
        @{
            role = "user"
            content = "Read facts.txt and answer with exactly one JSON object containing keys launch, team_size, sensor. Do not create or edit any file. Use the values associated with launch, team_size, and sensor in facts.txt."
        }
    )
    tools = $ToolDefinitions
    stream = $false
    options = @{
        num_ctx = $NumCtx
        num_predict = $NumPredict
        temperature = 0
    }
    keep_alive = 0
}

$RequestJson = $RequestObject | ConvertTo-Json -Depth 20
$RequestPath = Join-Path $RunDir "request.json"
$ResponsePath = Join-Path $RunDir "response.json"
$SummaryPath = Join-Path $RunDir "summary.json"
$MetadataPath = Join-Path $RunDir "metadata.json"

[System.IO.File]::WriteAllText(
    [System.IO.Path]::GetFullPath($RequestPath),
    $RequestJson,
    [System.Text.UTF8Encoding]::new($false)
)

$Metadata = [ordered]@{
    captured_at_utc = $Timestamp
    model = $Model
    base_url = $BaseUrl
    endpoint = "/api/chat"
    purpose = "diagnostic-only native structured tool transport smoke"
    executes_tools = $false
    prompt_case = "read-only-evidence-answer"
    tool_surface = @("read_file", "write_file")
    num_ctx = $NumCtx
    num_predict = $NumPredict
    temperature = 0
}

try {
    $VersionText = (& ollama --version 2>&1 | Out-String).Trim()
    $Metadata.ollama_version = $VersionText
}
catch {
    $Metadata.ollama_version = $null
}

$Metadata | ConvertTo-Json -Depth 10 | Set-Content -Path $MetadataPath -Encoding utf8

$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $Response = Invoke-RestMethod `
        -Uri ($BaseUrl.TrimEnd('/') + "/api/chat") `
        -Method Post `
        -ContentType "application/json" `
        -Body $RequestJson
}
catch {
    $Stopwatch.Stop()
    $Failure = [ordered]@{
        status = "request_error"
        model = $Model
        wall_time_ms = $Stopwatch.ElapsedMilliseconds
        error_type = $_.Exception.GetType().FullName
        error = $_.Exception.Message
        structured_tool_call_present = $false
        semantic_tool_selection = "unknown"
        argument_correctness = "unknown"
        protocol_parser_compatibility = "unknown"
        end_to_end_success = "not_applicable"
        run_directory = $RunDir
    }
    $Failure | ConvertTo-Json -Depth 10 | Set-Content -Path $SummaryPath -Encoding utf8
    $Failure | Format-List
    throw "Ollama transport smoke failed for $Model after preserving evidence in $RunDir"
}
$Stopwatch.Stop()

$ResponseJson = $Response | ConvertTo-Json -Depth 30
[System.IO.File]::WriteAllText(
    [System.IO.Path]::GetFullPath($ResponsePath),
    $ResponseJson,
    [System.Text.UTF8Encoding]::new($false)
)

$Message = $Response.message
$ToolCalls = @()
if ($null -ne $Message -and $null -ne $Message.tool_calls) {
    $ToolCalls = @($Message.tool_calls)
}

$Structured = $ToolCalls.Count -gt 0
$FirstName = $null
$FirstArguments = $null
if ($Structured) {
    $FirstName = $ToolCalls[0].function.name
    $FirstArguments = $ToolCalls[0].function.arguments
}

$Content = $null
if ($null -ne $Message) {
    $Content = $Message.content
}

$SemanticSelection = "unknown"
$ArgumentCorrectness = "unknown"
$ProtocolCompatibility = if ($Structured) { "pass" } else { "fail" }

if ($Structured) {
    $SemanticSelection = if ($FirstName -eq "read_file") { "pass" } else { "fail" }
    $ArgumentCorrectness = if (
        $null -ne $FirstArguments -and
        $FirstArguments.path -eq "facts.txt"
    ) { "pass" } else { "fail" }
}

$Summary = [ordered]@{
    status = "completed"
    model = $Model
    wall_time_ms = $Stopwatch.ElapsedMilliseconds
    structured_tool_call_present = $Structured
    tool_call_count = $ToolCalls.Count
    first_tool_name = $FirstName
    first_tool_arguments = $FirstArguments
    assistant_content = $Content
    done = $Response.done
    done_reason = $Response.done_reason
    semantic_tool_selection = $SemanticSelection
    argument_correctness = $ArgumentCorrectness
    protocol_parser_compatibility = $ProtocolCompatibility
    end_to_end_success = "not_applicable"
    end_to_end_detail = "Diagnostic transport smoke does not execute tools or score task completion."
    executes_tools = $false
    request_file = $RequestPath
    response_file = $ResponsePath
    metadata_file = $MetadataPath
    run_directory = $RunDir
}

$Summary | ConvertTo-Json -Depth 20 | Set-Content -Path $SummaryPath -Encoding utf8

Write-Host ""
Write-Host "=== OLLAMA TOOL TRANSPORT SMOKE ===" -ForegroundColor Cyan
Write-Host "Model:              $Model"
Write-Host "Wall time:          $($Stopwatch.ElapsedMilliseconds) ms"
Write-Host "Structured call:    $Structured"
Write-Host "Semantic selection: $SemanticSelection"
Write-Host "Arguments:          $ArgumentCorrectness"
Write-Host "Protocol:           $ProtocolCompatibility"
Write-Host "Run evidence:       $RunDir"
Write-Host ""

$Summary | Format-List
