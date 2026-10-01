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
$evidenceDir = Split-Path -Parent $RunJson
$roleStdout = Join-Path $evidenceDir 'role-turn.jsonl'
$roleStderr = Join-Path $evidenceDir 'role-turn.stderr.txt'
$intentStdout = Join-Path $evidenceDir 'intent-turn.jsonl'
$intentStderr = Join-Path $evidenceDir 'intent-turn.stderr.txt'

function RemainingSeconds {
  return [math]::Floor($WallSeconds - ((Get-Date) - $RunStartedAt).TotalSeconds)
}

function Write-RunRecord([string]$condition, $code, $roleCode = $null, $sessionId = $null) {
  $ended = Get-Date
  [ordered]@{
    startedAt = $RunStartedAt.ToString('o')
    endedAt = $ended.ToString('o')
    wallClockSeconds = [math]::Round(($ended-$RunStartedAt).TotalSeconds,3)
    configuredWallClockSeconds = $WallSeconds
    dshExitCode = $code
    roleTurnExitCode = $roleCode
    sessionId = $sessionId
    terminalCondition = $condition
    roleTurnEvents = $roleStdout
    roleTurnStderr = $roleStderr
    intentTurnEvents = $intentStdout
    intentTurnStderr = $intentStderr
  } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $RunJson -Encoding UTF8
}

function Invoke-DshTurn([string]$task, [string]$stdoutPath, [string]$stderrPath, [string]$sessionId = '') {
  $remaining = RemainingSeconds
  if ($remaining -le 0) { return [pscustomobject]@{ TimedOut=$true; ExitCode=$null } }

  $escapedDsh = $DshPath.Replace("'","''")
  $escapedBase = $BasePatch.Replace("'","''")
  $escapedCandidate = $CandidatePatch.Replace("'","''")
  $escapedTask = $task.Replace("'","''")
  $resume = ''
  if ($sessionId) {
    $escapedSession = $sessionId.Replace("'","''")
    $resume = " --session-id '$escapedSession'"
  }
  $command = "& '$escapedDsh' --profile headless --patch '$escapedBase' --patch '$escapedCandidate' --json$resume '$escapedTask'; exit " + '$LASTEXITCODE'
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))

  $psi = [Diagnostics.ProcessStartInfo]::new()
  $psi.FileName = 'powershell.exe'
  $psi.Arguments = "-NoProfile -EncodedCommand $encoded"
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true

  $p = [Diagnostics.Process]::new()
  $p.StartInfo = $psi
  [void]$p.Start()
  $stdoutTask = $p.StandardOutput.ReadToEndAsync()
  $stderrTask = $p.StandardError.ReadToEndAsync()

  $timedOut = -not $p.WaitForExit($remaining * 1000)
  if ($timedOut) {
    & taskkill.exe /PID $p.Id /T /F *> $null
    try { $p.WaitForExit() } catch {}
  }

  $stdout = $stdoutTask.GetAwaiter().GetResult()
  $stderr = $stderrTask.GetAwaiter().GetResult()
  Set-Content -LiteralPath $stdoutPath -Value $stdout -Encoding UTF8
  Set-Content -LiteralPath $stderrPath -Value $stderr -Encoding UTF8

  if ($stderr) { Write-Host $stderr.TrimEnd() }
  if ($stdout) {
    foreach ($line in ($stdout -split "`r?`n")) {
      if (-not $line.Trim()) { continue }
      try {
        $event = $line | ConvertFrom-Json
        if ($event.type -eq 'final' -and $event.text) { Write-Host $event.text }
      } catch {}
    }
  }

  return [pscustomobject]@{
    TimedOut = $timedOut
    ExitCode = if ($timedOut) { $null } else { $p.ExitCode }
  }
}

# Turn 1: assign the role and let DSH create a fresh durable Session.
$roleResult = Invoke-DshTurn $role $roleStdout $roleStderr
if ($roleResult.TimedOut) { Write-RunRecord 'wall_clock' $null $null $null; exit 124 }
if ($roleResult.ExitCode -ne 0) { Write-RunRecord 'runtime_error' $roleResult.ExitCode $roleResult.ExitCode $null; exit $roleResult.ExitCode }

$sessionId = $null
foreach ($line in (Get-Content -LiteralPath $roleStdout)) {
  if (-not $line.Trim()) { continue }
  try {
    $event = $line | ConvertFrom-Json
    if ($event.type -eq 'session' -and $event.id) { $sessionId = [string]$event.id; break }
  } catch {}
}
if (-not $sessionId) {
  Write-RunRecord 'runtime_error' 1 $roleResult.ExitCode $null
  Write-Error 'Role turn completed but no DSH session id was emitted.'
  exit 1
}

# Turn 2: resume the exact same Session and supply the project intent.
$intentResult = Invoke-DshTurn $pkg $intentStdout $intentStderr $sessionId
if ($intentResult.TimedOut) { Write-RunRecord 'wall_clock' $null $roleResult.ExitCode $sessionId; exit 124 }

$terminal = if ($intentResult.ExitCode -eq 0) { 'completed' } else { 'runtime_error' }
Write-RunRecord $terminal $intentResult.ExitCode $roleResult.ExitCode $sessionId
exit $intentResult.ExitCode