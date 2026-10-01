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

$utf8 = [Text.UTF8Encoding]::new($false)
$role = [IO.File]::ReadAllText($RolePrompt, $utf8)
$pkg = [IO.File]::ReadAllText($PackageFile, $utf8)
$evidenceDir = Split-Path -Parent $RunJson

$roleStdin = Join-Path $evidenceDir 'role-turn.stdin.txt'
$roleStdinMeta = Join-Path $evidenceDir 'role-turn.stdin.meta.json'
$roleStdout = Join-Path $evidenceDir 'role-turn.stdout.jsonl'
$roleStderr = Join-Path $evidenceDir 'role-turn.stderr.txt'
$intentStdin = Join-Path $evidenceDir 'intent-turn.stdin.txt'
$intentStdinMeta = Join-Path $evidenceDir 'intent-turn.stdin.meta.json'
$intentStdout = Join-Path $evidenceDir 'intent-turn.stdout.jsonl'
$intentStderr = Join-Path $evidenceDir 'intent-turn.stderr.txt'

function RemainingSeconds {
  return [math]::Floor($WallSeconds - ((Get-Date) - $RunStartedAt).TotalSeconds)
}

function Get-Sha256Hex([byte[]]$bytes) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
  }
  finally {
    $sha.Dispose()
  }
}

function Write-JsonUtf8([string]$path, $value) {
  $json = $value | ConvertTo-Json -Depth 8
  [IO.File]::WriteAllBytes($path, $utf8.GetBytes($json))
}

function Write-OutboundEvidence([string]$path, [string]$metaPath, [string]$text) {
  $bytes = $utf8.GetBytes($text)
  [IO.File]::WriteAllBytes($path, $bytes)
  Write-JsonUtf8 $metaPath ([ordered]@{
    path = $path
    utf16CodeUnits = $text.Length
    utf8Bytes = $bytes.Length
    sha256 = Get-Sha256Hex $bytes
  })
  return $bytes
}

function Write-RunRecord([string]$condition, $code, $roleCode = $null, $sessionId = $null) {
  $ended = Get-Date
  Write-JsonUtf8 $RunJson ([ordered]@{
    startedAt = $RunStartedAt.ToString('o')
    endedAt = $ended.ToString('o')
    wallClockSeconds = [math]::Round(($ended-$RunStartedAt).TotalSeconds,3)
    configuredWallClockSeconds = $WallSeconds
    dshExitCode = $code
    roleTurnExitCode = $roleCode
    sessionId = $sessionId
    terminalCondition = $condition
    roleTurnStdin = $roleStdin
    roleTurnStdinMeta = $roleStdinMeta
    roleTurnEvents = $roleStdout
    roleTurnStderr = $roleStderr
    intentTurnStdin = $intentStdin
    intentTurnStdinMeta = $intentStdinMeta
    intentTurnEvents = $intentStdout
    intentTurnStderr = $intentStderr
  })
}

function Invoke-DshTurn(
  [string]$task,
  [string]$stdinPath,
  [string]$stdinMetaPath,
  [string]$stdoutPath,
  [string]$stderrPath,
  [string]$sessionId = ''
) {
  $remaining = RemainingSeconds
  if ($remaining -le 0) {
    return [pscustomobject]@{ TimedOut=$true; ExitCode=$null }
  }

  foreach ($value in @($DshPath, $BasePatch, $CandidatePatch, $sessionId)) {
    if ($value -and $value.Contains('"')) {
      throw 'DSH path, patch path, and session id values must not contain a double quote.'
    }
  }

  $inputBytes = Write-OutboundEvidence $stdinPath $stdinMetaPath $task

  $resume = ''
  if ($sessionId) {
    $resume = ' --session-id "' + $sessionId + '"'
  }

  # DSH 0.1.6 headless reads "-" from stdin. The complete prompt therefore
  # bypasses Windows command-line parsing; the exact UTF-8 bytes saved above
  # are the same bytes written to the child stdin pipe.
  $nativeCommand = '"' + $DshPath + '" --profile headless --patch "' + $BasePatch +
    '" --patch "' + $CandidatePatch + '" --json' + $resume + ' -'

  $psi = [Diagnostics.ProcessStartInfo]::new()
  $psi.FileName = 'cmd.exe'
  $psi.Arguments = '/d /s /c "' + $nativeCommand + '"'
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardInput = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true

  $p = [Diagnostics.Process]::new()
  $p.StartInfo = $psi
  [void]$p.Start()

  $stdoutBuffer = [IO.MemoryStream]::new()
  $stderrBuffer = [IO.MemoryStream]::new()
  $stdoutTask = $p.StandardOutput.BaseStream.CopyToAsync($stdoutBuffer)
  $stderrTask = $p.StandardError.BaseStream.CopyToAsync($stderrBuffer)

  try {
    $p.StandardInput.BaseStream.Write($inputBytes, 0, $inputBytes.Length)
    $p.StandardInput.BaseStream.Flush()
    $p.StandardInput.Close()
  }
  catch {
    try { $p.Kill() } catch {}
    throw
  }

  $timedOut = -not $p.WaitForExit($remaining * 1000)
  if ($timedOut) {
    & taskkill.exe /PID $p.Id /T /F *> $null
    try { $p.WaitForExit() } catch {}
  }

  $stdoutTask.GetAwaiter().GetResult()
  $stderrTask.GetAwaiter().GetResult()

  $stdoutBytes = $stdoutBuffer.ToArray()
  $stderrBytes = $stderrBuffer.ToArray()
  $stdoutBuffer.Dispose()
  $stderrBuffer.Dispose()

  [IO.File]::WriteAllBytes($stdoutPath, $stdoutBytes)
  [IO.File]::WriteAllBytes($stderrPath, $stderrBytes)

  $stdout = $utf8.GetString($stdoutBytes)
  $stderr = $utf8.GetString($stderrBytes)

  if ($stderr) { Write-Host $stderr.TrimEnd() }
  if ($stdout) {
    foreach ($line in ($stdout -split "\r?\n")) {
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
$roleResult = Invoke-DshTurn $role $roleStdin $roleStdinMeta $roleStdout $roleStderr
if ($roleResult.TimedOut) {
  Write-RunRecord 'wall_clock' $null $null $null
  exit 124
}
if ($roleResult.ExitCode -ne 0) {
  Write-RunRecord 'runtime_error' $roleResult.ExitCode $roleResult.ExitCode $null
  exit $roleResult.ExitCode
}

$sessionId = $null
$roleOutput = [IO.File]::ReadAllText($roleStdout, $utf8)
foreach ($line in ($roleOutput -split "\r?\n")) {
  if (-not $line.Trim()) { continue }
  try {
    $event = $line | ConvertFrom-Json
    if ($event.type -eq 'session' -and $event.sessionId) {
      $sessionId = [string]$event.sessionId
      break
    }
  } catch {}
}
if (-not $sessionId) {
  Write-RunRecord 'runtime_error' 1 $roleResult.ExitCode $null
  Write-Host 'Role turn completed but no DSH session id was emitted.'
  exit 1
}

# Turn 2: resume the exact same Session and supply the project intent.
$intentResult = Invoke-DshTurn $pkg $intentStdin $intentStdinMeta $intentStdout $intentStderr $sessionId
if ($intentResult.TimedOut) {
  Write-RunRecord 'wall_clock' $null $roleResult.ExitCode $sessionId
  exit 124
}

$terminal = if ($intentResult.ExitCode -eq 0) { 'completed' } else { 'runtime_error' }
Write-RunRecord $terminal $intentResult.ExitCode $roleResult.ExitCode $sessionId
exit $intentResult.ExitCode
