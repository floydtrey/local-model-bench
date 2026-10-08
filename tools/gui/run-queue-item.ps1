# GUI-only output encoding adapter. All benchmark behavior belongs to the CLI.
# Keep this script parameterless: @args forwards names and values without a
# second set of parameter definitions or defaults.
$ErrorActionPreference = 'Stop'
$QueueUtf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $QueueUtf8
$OutputEncoding = $QueueUtf8
$env:PYTHONIOENCODING = 'utf-8'

& (Join-Path $PSScriptRoot '..\campaigns\run-all-roles.ps1') @args
exit $LASTEXITCODE
