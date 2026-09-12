param(
    [Parameter(Mandatory = $true)]
    [string]$ServerPath,

    [Parameter(Mandatory = $true)]
    [string]$ModelPath,

    [Parameter(Mandatory = $true)]
    [string]$ModelAlias,

    [Parameter(Mandatory = $true)]
    [string]$RoundLabel,

    [string[]]$Tasks = @(
        "repair-calculator-average",
        "add-json-report",
        "remove-legacy-mode"
    ),

    [ValidateSet("qwen_canonical", "qwen_25_compat", "function_xml", "json_call")]
    [string]$ToolProfile = "qwen_25_compat",

    [int]$Port = 18082,

    [int]$ContextSize = 32768,

    [int]$GpuLayers = 99,

    [int]$StartupTimeoutSeconds = 300,

    [string]$WorkspaceRoot = "local-state/construction-lab/workspaces",

    [string]$ResultRoot = "local-state/construction-lab/runs",

    [string]$ServerEvidenceRoot = "local-state/construction-lab/server-runs",

    [string]$CommandBackend = "docker",

    [string]$DockerImage = "python:3.12-slim",

    [string[]]$ServerArgs = @()
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-ModelParts {
    param([Parameter(Mandatory = $true)][string]$FirstPart)
    $Item = Get-Item -LiteralPath $FirstPart -ErrorAction Stop
    if ($Item.Name -match '^(?<prefix>.+)-(?<part>\d{5})-of-(?<total>\d{5})\.gguf$') {
        $Total = [int]$Matches.total
        if ([int]$Matches.part -ne 1) {
            throw "ModelPath must identify the first GGUF shard."
        }
        $Parts = @()
        for ($Index = 1; $Index -le $Total; $Index++) {
            $Name = "{0}-{1:D5}-of-{2:D5}.gguf" -f $Matches.prefix, $Index, $Total
            $Path = Join-Path $Item.DirectoryName $Name
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
                throw "Missing GGUF shard: $Path"
            }
            $Parts += [System.IO.Path]::GetFullPath($Path)
        }
        return $Parts
    }
    return @([System.IO.Path]::GetFullPath($Item.FullName))
}

function Test-PortAvailable {
    param([Parameter(Mandatory = $true)][int]$CandidatePort)
    $Listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        $CandidatePort
    )
    try {
        $Listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        $Listener.Stop()
    }
}

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}
if (-not (Test-PortAvailable $Port)) {
    throw "Refusing to start managed llama.cpp because 127.0.0.1:$Port is already in use."
}

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $Here)
$BatchScript = Join-Path $Here "run-construction-batch.ps1"
$ResolvedServer = [System.IO.Path]::GetFullPath(
    (Get-Item -LiteralPath $ServerPath -ErrorAction Stop).FullName
)
$ModelParts = @(Get-ModelParts $ModelPath)
$ResolvedModel = $ModelParts[0]
$BaseUrl = "http://127.0.0.1:$Port"
$ApiKeyEnvironmentName = "LOCALBENCH_CONSTRUCTION_LLAMA_CPP_API_KEY"
$PriorApiKey = [Environment]::GetEnvironmentVariable($ApiKeyEnvironmentName, "Process")
$ApiKeyBytes = New-Object byte[] 32
$RandomNumberGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $RandomNumberGenerator.GetBytes($ApiKeyBytes)
}
finally {
    $RandomNumberGenerator.Dispose()
}
$SessionApiKey = ([System.BitConverter]::ToString($ApiKeyBytes) -replace "-", "").ToLowerInvariant()

$ResolvedServerEvidenceRoot = if ([System.IO.Path]::IsPathRooted($ServerEvidenceRoot)) {
    [System.IO.Path]::GetFullPath($ServerEvidenceRoot)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $ServerEvidenceRoot))
}
$EvidenceRoot = Join-Path $ResolvedServerEvidenceRoot $RoundLabel
New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
$ServerStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$ServerRun = Join-Path $EvidenceRoot ("{0}-{1}" -f $ServerStamp, [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $ServerRun -ErrorAction Stop | Out-Null
$StdoutLog = Join-Path $ServerRun "llama-server.stdout.log"
$StderrLog = Join-Path $ServerRun "llama-server.stderr.log"
$ProvenanceFile = Join-Path $ServerRun "provider-provenance.json"

$PriorErrorActionPreferenceForVersion = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $VersionOutput = @(& $ResolvedServer --version 2>&1)
    $VersionExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PriorErrorActionPreferenceForVersion
}
if ($VersionExitCode -ne 0) {
    throw "llama-server --version failed with exit code $VersionExitCode."
}
$VersionText = (($VersionOutput | ForEach-Object { $_.ToString() }) -join "`n").Trim()
$ModelEvidence = @(
    foreach ($Part in $ModelParts) {
        $Item = Get-Item -LiteralPath $Part
        [ordered]@{
            path = $Part
            size_bytes = $Item.Length
            sha256 = (Get-FileHash -LiteralPath $Part -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
)
$ServerEvidence = [ordered]@{
    path = $ResolvedServer
    size_bytes = (Get-Item -LiteralPath $ResolvedServer).Length
    sha256 = (Get-FileHash -LiteralPath $ResolvedServer -Algorithm SHA256).Hash.ToLowerInvariant()
    version = $VersionText
}

$Arguments = @(
    "-m", $ResolvedModel,
    "--alias", $ModelAlias,
    "--host", "127.0.0.1",
    "--port", [string]$Port,
    "--api-key", $SessionApiKey,
    "--no-webui",
    "--ctx-size", [string]$ContextSize,
    "--gpu-layers", [string]$GpuLayers,
    "--parallel", "1",
    "--jinja"
) + @($ServerArgs)

$Process = $null
try {
    [Environment]::SetEnvironmentVariable(
        $ApiKeyEnvironmentName,
        $SessionApiKey,
        "Process"
    )
    $Process = Start-Process `
        -FilePath $ResolvedServer `
        -ArgumentList $Arguments `
        -WorkingDirectory (Split-Path -Parent $ResolvedServer) `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru

    $Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $Headers = @{ Authorization = "Bearer $SessionApiKey" }
    $Ready = $false
    while ((Get-Date) -lt $Deadline) {
        if ($Process.HasExited) {
            $Tail = if (Test-Path -LiteralPath $StderrLog) {
                (Get-Content -LiteralPath $StderrLog -Tail 80) -join "`n"
            }
            else {
                ""
            }
            throw "llama-server exited during startup with code $($Process.ExitCode): $Tail"
        }
        try {
            $null = Invoke-RestMethod `
                -Method Get `
                -Uri "$BaseUrl/v1/models" `
                -Headers $Headers `
                -TimeoutSec 3
            $Ready = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $Ready) {
        throw "llama-server did not become ready within $StartupTimeoutSeconds seconds."
    }

    $Provenance = [ordered]@{
        schema_version = "construction-llama-cpp-provider-provenance:v1"
        model_alias = $ModelAlias
        model_parts = $ModelEvidence
        server = $ServerEvidence
        base_url = $BaseUrl
        process_id = $Process.Id
        launch_arguments_without_api_key = @(
            for ($Index = 0; $Index -lt $Arguments.Count; $Index++) {
                if ($Index -gt 0 -and $Arguments[$Index - 1] -eq "--api-key") {
                    "<redacted>"
                }
                else {
                    $Arguments[$Index]
                }
            }
        )
        tool_profile = $ToolProfile
        started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
    }
    $Provenance | ConvertTo-Json -Depth 20 | Set-Content `
        -LiteralPath $ProvenanceFile `
        -Encoding utf8

    & $BatchScript `
        -Models @($ModelAlias) `
        -Tasks $Tasks `
        -RoundLabel $RoundLabel `
        -WorkspaceRoot $WorkspaceRoot `
        -ResultRoot $ResultRoot `
        -Provider "openai_compatible" `
        -ToolProfile $ToolProfile `
        -BaseUrl $BaseUrl `
        -ApiKeyEnv $ApiKeyEnvironmentName `
        -ProviderProvenanceFile $ProvenanceFile `
        -CommandBackend $CommandBackend `
        -DockerImage $DockerImage
}
finally {
    if ($null -ne $Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(15000) | Out-Null
    }
    [Environment]::SetEnvironmentVariable(
        $ApiKeyEnvironmentName,
        $PriorApiKey,
        "Process"
    )
}

Write-Host "Managed llama.cpp evidence: $ServerRun" -ForegroundColor Green
