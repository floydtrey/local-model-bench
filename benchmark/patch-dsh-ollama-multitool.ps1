param(
  [string]$DshHome = (Join-Path $env:USERPROFILE '.dsh'),
  [switch]$Restore
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dsh = Join-Path $env:APPDATA 'npm\dsh.cmd'
$pluginRoot = Join-Path $DshHome 'profiles\headless\node_modules\@zhangyi\dsh-llm-ollama'
$packagePath = Join-Path $pluginRoot 'package.json'
$indexPath = Join-Path $pluginRoot 'lib\index.js'
$backupRoot = Join-Path $repo 'local-state\runtime-backups\dsh-llm-ollama-0.1.17'
$backupPath = Join-Path $backupRoot 'index.js.original'
$utf8 = [Text.UTF8Encoding]::new($false)

foreach ($required in @($dsh,$packagePath,$indexPath)) {
  if (-not (Test-Path -LiteralPath $required)) { throw "Missing required path: $required" }
}

$dshVersion = (& $dsh --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not read DSH version.' }
if ($dshVersion -ne '0.1.6-alpha.2') {
  throw "Refusing patch: expected DSH 0.1.6-alpha.2, found '$dshVersion'."
}

$package = Get-Content -LiteralPath $packagePath -Raw | ConvertFrom-Json
$pluginVersion = [string]$package.version
if ($pluginVersion -ne '0.1.17') {
  throw "Refusing patch: expected @zhangyi/dsh-llm-ollama 0.1.17, found '$pluginVersion'."
}

if ($Restore) {
  if (-not (Test-Path -LiteralPath $backupPath)) { throw "Original backup not found: $backupPath" }
  Copy-Item -LiteralPath $backupPath -Destination $indexPath -Force
  Write-Host 'Restored original dsh-llm-ollama lib\index.js.'
  Write-Host "Source: $backupPath"
  exit 0
}

$source = [IO.File]::ReadAllText($indexPath,$utf8)
$old = "const slot = call.index !== undefined && typeof call.index === 'number' ? call.index : 0"
$new = @"
const slot =
                      typeof call.index === 'number'
                        ? call.index
                        : typeof fn.index === 'number'
                          ? fn.index
                          : typeof call.id === 'string' && call.id.length > 0
                            ? call.id
                            : 0
"@.TrimEnd()

$alreadyPatched = $source.Contains("typeof fn.index === 'number'") -and $source.Contains("typeof call.id === 'string' && call.id.length > 0")
if ($alreadyPatched) {
  Write-Host 'Compatibility patch is already present.'
  Write-Host "DSH:    $dshVersion"
  Write-Host "Plugin: $pluginVersion"
  Write-Host "File:   $indexPath"
  exit 0
}

$first = $source.IndexOf($old,[StringComparison]::Ordinal)
if ($first -lt 0) {
  throw 'Expected 0.1.17 slot-selection code was not found. Refusing to guess at a different source layout.'
}
$second = $source.IndexOf($old,$first + $old.Length,[StringComparison]::Ordinal)
if ($second -ge 0) { throw 'Expected slot-selection code occurs more than once. Refusing ambiguous patch.' }

New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $backupPath)) {
  Copy-Item -LiteralPath $indexPath -Destination $backupPath
}

$beforeHash = (Get-FileHash -LiteralPath $indexPath -Algorithm SHA256).Hash.ToLowerInvariant()
$patched = $source.Substring(0,$first) + $new + $source.Substring($first + $old.Length)
[IO.File]::WriteAllText($indexPath,$patched,$utf8)
$afterHash = (Get-FileHash -LiteralPath $indexPath -Algorithm SHA256).Hash.ToLowerInvariant()

$verify = [IO.File]::ReadAllText($indexPath,$utf8)
if (-not $verify.Contains("typeof fn.index === 'number'") -or -not $verify.Contains("typeof call.id === 'string' && call.id.length > 0")) {
  Copy-Item -LiteralPath $backupPath -Destination $indexPath -Force
  throw 'Post-write verification failed. Original file restored.'
}

Write-Host ''
Write-Host 'Applied native Ollama multi-tool compatibility patch.'
Write-Host "DSH:         $dshVersion"
Write-Host "Plugin:      $pluginVersion"
Write-Host "Target:      $indexPath"
Write-Host "Original:    $backupPath"
Write-Host "Before SHA:  $beforeHash"
Write-Host "After SHA:   $afterHash"
Write-Host ''
Write-Host 'Behavior: call.index -> function.index -> call.id fallback.'
Write-Host 'No model run was performed.'
