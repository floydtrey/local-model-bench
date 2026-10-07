[CmdletBinding()]
param(
    [ValidateSet('validate', 'preflight', 'smoke', 'shared-screen', 'shared-qualification', 'roles')]
    [string]$Stage = 'validate',
    [string]$SmokeRun,
    [string]$SharedRun,
    [ValidateSet('planner', 'governor', 'worker', 'tester', 'reviewer', 'all')]
    [string[]]$Role,
    [ValidateSet('screen', 'qualification')]
    [string]$Phase = 'screen',
    [string]$GovernorRoot,
    [string]$OutputRoot,
    [string]$ProfilePath,
    [string]$PythonExe
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
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

$Arguments = @('-u', '-m', 'localbench.v2.flashnext_campaign', $Stage, '--repo-root', $RepoRoot, '--phase', $Phase)
if ($SmokeRun) { $Arguments += @('--smoke-run', $SmokeRun) }
if ($SharedRun) { $Arguments += @('--shared-run', $SharedRun) }
if ($GovernorRoot) { $Arguments += @('--governor-root', $GovernorRoot) }
if ($OutputRoot) { $Arguments += @('--output-root', $OutputRoot) }
if ($ProfilePath) { $Arguments += @('--profile', $ProfilePath) }
foreach ($SelectedRole in $Role) { $Arguments += @('--role', $SelectedRole) }

# Resolve this checkout's source explicitly. This does not install dependencies,
# select another runtime, or start a server when Stage is validate/preflight.
$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $RepoRoot 'src'
    if ($PreviousPythonPath) {
        $env:PYTHONPATH += [IO.Path]::PathSeparator + $PreviousPythonPath
    }
    & $PythonExe @PythonPrefix @Arguments
    $CampaignExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
exit $CampaignExitCode
