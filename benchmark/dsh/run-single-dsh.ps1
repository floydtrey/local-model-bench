param(
  [Parameter(Mandatory=$true)][string]$DshPath,
  [Parameter(Mandatory=$true)][string]$BasePatch,
  [Parameter(Mandatory=$true)][string]$CandidatePatch,
  [Parameter(Mandatory=$true)][string]$RolePrompt,
  [Parameter(Mandatory=$true)][string]$PackageFile,
  [Parameter(Mandatory=$true)][int]$WallSeconds,
  [Parameter(Mandatory=$true)][string]$RunJson,
  [Parameter(Mandatory=$true)][datetime]$RunStartedAt
)

$ErrorActionPreference = 'Stop'

$role = Get-Content -LiteralPath $RolePrompt -Raw
$pkg = Get-Content -LiteralPath $PackageFile -Raw
$task = $role + [Environment]::NewLine + [Environment]::NewLine + $pkg

$remaining = [math]::Floor($WallSeconds - ((Get-Date) - $RunStartedAt).TotalSeconds)
if ($remaining -le 0) {
  $ended = Get-Date
  [ordered]@{
    startedAt = $RunStartedAt.ToString('o')
    endedAt = $ended.ToString('o')
    wallClockSeconds = [math]::Round(($ended-$RunStartedAt).TotalSeconds,3)
    configuredWallClockSeconds = $WallSeconds
    dshExitCode = $null
    terminalCondition = 'wall_clock'
  } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $RunJson -Encoding UTF8
  exit 124
}

$escapedDsh = $DshPath.Replace("'","''")
$escapedBase = $BasePatch.Replace("'","''")
$escapedCandidate = $CandidatePatch.Replace("'","''")
$escapedTask = $task.Replace("'","''")
$command = "& '$escapedDsh' --profile headless --patch '$escapedBase' --patch '$escapedCandidate' '$escapedTask'; exit " + '$LASTEXITCODE'

$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = 'powershell.exe'
$psi.Arguments = "-NoProfile -EncodedCommand $encoded"
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $false

$p = [Diagnostics.Process]::new()
$p.StartInfo = $psi
[void]$p.Start()

$timedOut = -not $p.WaitForExit($remaining * 1000)
if ($timedOut) {
  & taskkill.exe /PID $p.Id /T /F | Out-Null
} else {
  $p.WaitForExit()
}

$ended = Get-Date
$exitCode = if ($timedOut) { $null } else { $p.ExitCode }
$terminal = if ($timedOut) { 'wall_clock' } elseif ($exitCode -eq 0) { 'completed' } else { 'runtime_error' }

[ordered]@{
  startedAt = $RunStartedAt.ToString('o')
  endedAt = $ended.ToString('o')
  wallClockSeconds = [math]::Round(($ended-$RunStartedAt).TotalSeconds,3)
  configuredWallClockSeconds = $WallSeconds
  dshExitCode = $exitCode
  terminalCondition = $terminal
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $RunJson -Encoding UTF8

if ($timedOut) { exit 124 }
exit $exitCode
