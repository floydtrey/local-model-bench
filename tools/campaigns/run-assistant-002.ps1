[CmdletBinding()]
param(
    [ValidateSet('validate','prepare','self-test','assess','run','probe','interop')][string]$Action = 'validate',
    [string]$Model,
    [ValidateSet('screen','qualification')][string]$Phase = 'screen',
    [ValidateSet('T01','T02','T03','T04','T05','T06')][string]$Through = 'T01',
    [ValidateSet('T01','T02','T03','T04','T05','T06')][string]$Task = 'T06',
    [ValidateSet('planner','governor','tester','reviewer')][string]$Role,
    [string]$GovernorRoot, [string]$PlanFile, [string]$InputRun,
    [string]$RunDir, [string]$JournalRun, [string]$OutputRoot,
    [int]$ContextTokens = 32768, [int]$MaxOutputTokens = 8192,
    [double]$TimeoutSeconds = 600, [double]$KeepAliveSeconds = 3600,
    [switch]$AllowHostExecution, [string]$PythonExe
)
$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Prefix = @()
if (-not $PythonExe) {
    $LocalPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $LocalPython -PathType Leaf) { $PythonExe = $LocalPython }
    elseif (Get-Command py.exe -ErrorAction SilentlyContinue) { $PythonExe = 'py.exe'; $Prefix = @('-3') }
    elseif (Get-Command python.exe -ErrorAction SilentlyContinue) { $PythonExe = 'python.exe' }
    else { throw 'Python 3.10+ is required; supply -PythonExe.' }
}
$Arguments = @('-u','-m','localbench.assistant002',$Action,'--repo-root',$RepoRoot,
    '--phase',$Phase,'--through',$Through,'--task',$Task,
    '--context-tokens',"$ContextTokens",'--max-output-tokens',"$MaxOutputTokens",
    '--timeout-seconds',$TimeoutSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--keep-alive-seconds',$KeepAliveSeconds.ToString([Globalization.CultureInfo]::InvariantCulture))
foreach ($Pair in @(@('--model',$Model),@('--role',$Role),@('--governor-root',$GovernorRoot),
    @('--plan-file',$PlanFile),@('--input-run',$InputRun),@('--run-dir',$RunDir),
    @('--journal-run',$JournalRun),@('--output-root',$OutputRoot))) {
    if ($Pair[1]) { $Arguments += $Pair }
}
if ($AllowHostExecution) { $Arguments += '--allow-host-execution' }
$Previous = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $RepoRoot 'src'
    if ($Previous) { $env:PYTHONPATH += [IO.Path]::PathSeparator + $Previous }
    & $PythonExe @Prefix @Arguments
    $ExitCode = $LASTEXITCODE
} finally { $env:PYTHONPATH = $Previous }
exit $ExitCode
