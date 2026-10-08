[CmdletBinding()]
param(
    [ValidateSet('ollama')]
    [string]$Runtime = 'ollama',

    [Parameter(Mandatory=$true)]
    [string]$Model,

    [ValidateSet('screen', 'qualification')]
    [string]$Phase = 'screen',

    [Parameter(Mandatory=$true)]
    [string]$GovernorRoot,

    [string]$BaseUrl = 'http://127.0.0.1:11434',
    [int]$ContextTokens = 32768,
    [int]$MaxOutputTokens = 8192,
    [double]$TimeoutSeconds = 600,
    [double]$KeepAliveSeconds = 3600,
    [string]$OutputRoot,
    [string]$PythonExe
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

if ($Runtime -ne 'ollama') {
    throw "Only the Ollama runtime is implemented by this generic entrypoint today."
}

$PythonPrefix = @()
if (-not $PythonExe) {
    $LocalPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $LocalPython -PathType Leaf) {
        $PythonExe = $LocalPython
    } elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $PythonExe = 'py.exe'
        $PythonPrefix = @('-3')
    } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        $PythonExe = 'python.exe'
    } else {
        throw 'Python 3.10+ is required. Pass -PythonExe with an existing Python executable.'
    }
}

$Arguments = @(
    '-u', '-m', 'localbench.v2.ollama_role_campaign',
    '--repo-root', $RepoRoot,
    '--model', $Model,
    '--phase', $Phase,
    '--governor-root', $GovernorRoot,
    '--base-url', $BaseUrl,
    '--context-tokens', "$ContextTokens",
    '--max-output-tokens', "$MaxOutputTokens",
    '--timeout-seconds', "$TimeoutSeconds",
    '--keep-alive-seconds', "$KeepAliveSeconds"
)
if ($OutputRoot) { $Arguments += @('--output-root', $OutputRoot) }

$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $RepoRoot 'src'
    if ($PreviousPythonPath) {
        $env:PYTHONPATH += [IO.Path]::PathSeparator + $PreviousPythonPath
    }
    & $PythonExe @PythonPrefix @Arguments
    $ExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
exit $ExitCode
