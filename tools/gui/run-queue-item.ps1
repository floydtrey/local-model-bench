# GUI-only output encoding adapter. All benchmark behavior belongs to the CLI.
# Keep this script parameterless: @args forwards names and values without a
# second set of parameter definitions or defaults.
$ErrorActionPreference = 'Stop'
$QueueUtf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $QueueUtf8
$OutputEncoding = $QueueUtf8
$env:PYTHONIOENCODING = 'utf-8'

# GUI-only dispatch selector, limited to approved checked-in scripts.
$Forwarded = @($args)
$Campaign = 'roles'
if ($Forwarded.Count -ge 2 -and $Forwarded[0] -eq '-QueueBenchmark') {
    $Campaign = [string]$Forwarded[1]
    $Forwarded = @($Forwarded | Select-Object -Skip 2)
}
switch ($Campaign) {
    'roles'         { $Runner = 'run-all-roles.ps1' }
    'assistant-001' { $Runner = 'run-assistant-001.ps1' }
    'assistant-002' { $Runner = 'run-assistant-002.ps1' }
    default { throw "Unsupported GUI benchmark: $Campaign" }
}
& (Join-Path $PSScriptRoot ('..\campaigns\' + $Runner)) @Forwarded
exit $LASTEXITCODE
