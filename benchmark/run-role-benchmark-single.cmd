@echo off
setlocal EnableExtensions

rem Generic Role Qualification v1 single-run launcher.
rem Usage:
rem   run-role-benchmark-single.cmd <candidate-patch> <role-prompt> <package> <output-dir> [wall-clock-seconds]
rem
rem wall-clock-seconds defaults to 600.

if "%~4"=="" (
  echo Usage:
  echo   %~nx0 ^<candidate-patch^> ^<role-prompt^> ^<package^> ^<output-dir^> [wall-clock-seconds]
  exit /b 2
)

set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

for %%I in ("%~1") do set "CANDIDATE_PATCH=%%~fI"
for %%I in ("%~2") do set "ROLE_PROMPT=%%~fI"
for %%I in ("%~3") do set "PACKAGE_FILE=%%~fI"
for %%I in ("%~4") do set "OUTPUT_DIR=%%~fI"

set "WALL_SECONDS=%~5"
if "%WALL_SECONDS%"=="" set "WALL_SECONDS=600"

set "DSH=%APPDATA%\npm\dsh.cmd"
set "BASE_PATCH=%REPO%\benchmark\dsh\role-qualification-v1.patch.yml"
set "DSH_HOME=%REPO%\local-state\role-qualification-v1\dsh-home"
set "OBSERVER=%REPO%\benchmark\dsh\passive-observer.mjs"
set "OBS_STATE=%OUTPUT_DIR%\observer-state.json"
set "OBS_JSON=%OUTPUT_DIR%\observations.json"
set "RUN_JSON=%OUTPUT_DIR%\run.json"
set "OLLAMA_PID_FILE=%OUTPUT_DIR%\ollama.pid"
set "DSH_TELEMETRY_DISABLED=1"
set "ROLE_BENCHMARK_LOCAL_KEY=local-benchmark-placeholder"
set "STARTED_OLLAMA=0"

if not exist "%DSH%" (
  echo ERROR: DSH not found at "%DSH%"
  exit /b 2
)
if not exist "%BASE_PATCH%" (
  echo ERROR: Missing "%BASE_PATCH%"
  exit /b 2
)
if not exist "%CANDIDATE_PATCH%" (
  echo ERROR: Missing candidate patch "%CANDIDATE_PATCH%"
  exit /b 2
)
if not exist "%ROLE_PROMPT%" (
  echo ERROR: Missing role prompt "%ROLE_PROMPT%"
  exit /b 2
)
if not exist "%PACKAGE_FILE%" (
  echo ERROR: Missing package "%PACKAGE_FILE%"
  exit /b 2
)
if exist "%OUTPUT_DIR%" (
  echo ERROR: Output directory already exists "%OUTPUT_DIR%"
  exit /b 2
)

where node.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: node.exe is not available on PATH.
  exit /b 2
)

where ollama.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: ollama.exe is not available on PATH.
  exit /b 2
)

mkdir "%OUTPUT_DIR%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Could not create output directory "%OUTPUT_DIR%"
  exit /b 2
)

copy /y "%ROLE_PROMPT%" "%OUTPUT_DIR%\role-prompt.txt" >nul
copy /y "%PACKAGE_FILE%" "%OUTPUT_DIR%\package.txt" >nul
copy /y "%CANDIDATE_PATCH%" "%OUTPUT_DIR%\candidate-patch.yml" >nul

if not exist "%DSH_HOME%" mkdir "%DSH_HOME%" >nul 2>&1

echo.
echo Role Qualification v1 - single run
echo Candidate patch: %CANDIDATE_PATCH%
echo Role prompt:     %ROLE_PROMPT%
echo Package:         %PACKAGE_FILE%
echo Output:          %OUTPUT_DIR%
echo Wall clock:      %WALL_SECONDS% seconds
echo.

powershell.exe -NoProfile -Command ^
  "try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"

if errorlevel 1 (
  echo Ollama API is offline. Starting a temporary Ollama server...
  powershell.exe -NoProfile -Command ^
    "$p = Start-Process -FilePath 'ollama.exe' -ArgumentList 'serve' -WindowStyle Hidden -PassThru; Set-Content -LiteralPath $env:OLLAMA_PID_FILE -Value $p.Id -NoNewline"
  if errorlevel 1 (
    echo ERROR: Failed to start Ollama.
    exit /b 3
  )
  set "STARTED_OLLAMA=1"

  echo Waiting for Ollama API...
  powershell.exe -NoProfile -Command ^
    "$deadline = (Get-Date).AddSeconds(30); do { try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Milliseconds 500 } } while ((Get-Date) -lt $deadline); exit 1"
  if errorlevel 1 (
    echo ERROR: Ollama did not become ready within 30 seconds.
    goto :cleanup_fail
  )
) else (
  echo Ollama API is already running. It will be left running.
)

node "%OBSERVER%" before "%OBS_STATE%" "%DSH_HOME%"
if errorlevel 1 (
  echo ERROR: Failed to snapshot pre-run DSH state.
  goto :cleanup_fail
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$started = Get-Date;" ^
  "$role = Get-Content -LiteralPath $env:ROLE_PROMPT -Raw;" ^
  "$pkg = Get-Content -LiteralPath $env:PACKAGE_FILE -Raw;" ^
  "$task = $role + [Environment]::NewLine + [Environment]::NewLine + $pkg;" ^
  "$psi = New-Object System.Diagnostics.ProcessStartInfo;" ^
  "$psi.FileName = $env:ComSpec;" ^
  "$escapedTask = $task.Replace('"','\"');" ^
  "$psi.Arguments = '/d /s /c ""' + $env:DSH + '" --profile headless --patch "' + $env:BASE_PATCH + '" --patch "' + $env:CANDIDATE_PATCH + '" "' + $escapedTask + '""';" ^
  "$psi.UseShellExecute = $false;" ^
  "$psi.RedirectStandardOutput = $true;" ^
  "$psi.RedirectStandardError = $true;" ^
  "$psi.CreateNoWindow = $true;" ^
  "$p = New-Object System.Diagnostics.Process;" ^
  "$p.StartInfo = $psi;" ^
  "[void]$p.Start();" ^
  "$outTask = $p.StandardOutput.ReadToEndAsync();" ^
  "$errTask = $p.StandardError.ReadToEndAsync();" ^
  "$timedOut = -not $p.WaitForExit([int]$env:WALL_SECONDS * 1000);" ^
  "if ($timedOut) { try { taskkill /PID $p.Id /T /F | Out-Null } catch {} } else { $p.WaitForExit() };" ^
  "$stdout = $outTask.GetAwaiter().GetResult();" ^
  "$stderr = $errTask.GetAwaiter().GetResult();" ^
  "if ($stdout) { [Console]::Out.Write($stdout) };" ^
  "if ($stderr) { [Console]::Error.Write($stderr) };" ^
  "$ended = Get-Date;" ^
  "$exitCode = if ($timedOut) { $null } else { $p.ExitCode };" ^
  "$terminal = if ($timedOut) { 'wall_clock' } elseif ($exitCode -eq 0) { 'completed' } else { 'runtime_error' };" ^
  "$run = [ordered]@{ startedAt=$started.ToString('o'); endedAt=$ended.ToString('o'); wallClockSeconds=[math]::Round(($ended-$started).TotalSeconds,3); configuredWallClockSeconds=[int]$env:WALL_SECONDS; dshExitCode=$exitCode; terminalCondition=$terminal; runnerStartedOllama=($env:STARTED_OLLAMA -eq '1'); candidatePatch=$env:CANDIDATE_PATCH; rolePrompt=$env:ROLE_PROMPT; package=$env:PACKAGE_FILE };" ^
  "$run | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $env:RUN_JSON -Encoding UTF8;" ^
  "if ($timedOut) { exit 124 } elseif ($exitCode -is [int]) { exit $exitCode } else { exit 1 }"

set "RC=%ERRORLEVEL%"

node "%OBSERVER%" after "%OBS_STATE%" "%DSH_HOME%" "%OBS_JSON%" "%RC%"
if errorlevel 1 echo WARNING: Passive post-run observation failed.

if "%STARTED_OLLAMA%"=="1" (
  echo Stopping temporary Ollama server started by this launcher...
  powershell.exe -NoProfile -Command ^
    "if (Test-Path -LiteralPath $env:OLLAMA_PID_FILE) { $pidValue = [int](Get-Content -LiteralPath $env:OLLAMA_PID_FILE -Raw); Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $env:OLLAMA_PID_FILE -Force -ErrorAction SilentlyContinue }"
)

echo.
echo Single-run exit code: %RC%
exit /b %RC%

:cleanup_fail
if "%STARTED_OLLAMA%"=="1" (
  echo Stopping temporary Ollama server started by this launcher...
  powershell.exe -NoProfile -Command ^
    "if (Test-Path -LiteralPath $env:OLLAMA_PID_FILE) { $pidValue = [int](Get-Content -LiteralPath $env:OLLAMA_PID_FILE -Raw); Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $env:OLLAMA_PID_FILE -Force -ErrorAction SilentlyContinue }"
)
exit /b 3
