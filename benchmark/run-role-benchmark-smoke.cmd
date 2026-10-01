@echo off
setlocal EnableExtensions

rem Role Qualification v1 smoke launcher.
rem This proves the isolated DSH path only. It does not produce benchmark evidence.

set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "DSH=%APPDATA%\npm\dsh.cmd"
set "BASE_PATCH=%REPO%\benchmark\dsh\role-qualification-v1.patch.yml"
set "MODEL_PATCH=%REPO%\benchmark\dsh\smoke-qwen35-9b.patch.yml"
set "TASK_FILE=%REPO%\benchmark\smoke\planner-path-smoke.txt"
set "DSH_HOME=%REPO%\local-state\role-qualification-v1\dsh-home"
set "OLLAMA_PID_FILE=%REPO%\local-state\role-qualification-v1\ollama-smoke.pid"
set "OBSERVER=%REPO%\benchmark\dsh\passive-observer.mjs"
set "OBS_STATE=%REPO%\local-state\role-qualification-v1\smoke-observer-state.json"
set "OBS_JSON=%REPO%\local-state\role-qualification-v1\smoke-observations.json"
set "CONSOLE_LOG=%REPO%\local-state\role-qualification-v1\smoke-console.log"
set "DSH_TELEMETRY_DISABLED=1"
set "ROLE_BENCHMARK_LOCAL_KEY=local-smoke-placeholder"
set "STARTED_OLLAMA=0"

if not exist "%DSH%" (
  echo ERROR: DSH not found at "%DSH%"
  exit /b 2
)
if not exist "%BASE_PATCH%" (
  echo ERROR: Missing "%BASE_PATCH%"
  exit /b 2
)
if not exist "%MODEL_PATCH%" (
  echo ERROR: Missing "%MODEL_PATCH%"
  exit /b 2
)
if not exist "%TASK_FILE%" (
  echo ERROR: Missing "%TASK_FILE%"
  exit /b 2
)
if not exist "%OBSERVER%" (
  echo ERROR: Missing "%OBSERVER%"
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

if not exist "%DSH_HOME%" mkdir "%DSH_HOME%" >nul 2>&1
if exist "%OLLAMA_PID_FILE%" del /q "%OLLAMA_PID_FILE%" >nul 2>&1

echo.
echo Role Qualification v1 - execution path smoke
echo DSH_HOME: %DSH_HOME%
echo Model: qwen3.5:9b
echo.
echo This run is NOT a benchmark result.
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

powershell.exe -NoProfile -Command ^
  "$tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5; if ($tags.models.name -contains 'qwen3.5:9b') { exit 0 } else { exit 1 }"
if errorlevel 1 (
  echo ERROR: Required model qwen3.5:9b is not installed in Ollama.
  echo Run: ollama pull qwen3.5:9b
  goto :cleanup_fail
)

echo Ollama is ready and qwen3.5:9b is installed.
echo Starting DSH smoke...

node "%OBSERVER%" before "%OBS_STATE%" "%DSH_HOME%"
if errorlevel 1 (
  echo ERROR: Failed to snapshot pre-run DSH sessions.
  goto :cleanup_fail
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$task = Get-Content -LiteralPath $env:TASK_FILE -Raw; & $env:DSH --profile headless --patch $env:BASE_PATCH --patch $env:MODEL_PATCH $task; exit $LASTEXITCODE"

set "RC=%ERRORLEVEL%"

node "%OBSERVER%" after "%OBS_STATE%" "%DSH_HOME%" "%OBS_JSON%" "%RC%"
if errorlevel 1 echo WARNING: Passive post-run observation failed.

if "%STARTED_OLLAMA%"=="1" (
  echo Stopping temporary Ollama server started by this launcher...
  powershell.exe -NoProfile -Command ^
    "if (Test-Path -LiteralPath $env:OLLAMA_PID_FILE) { $pidValue = [int](Get-Content -LiteralPath $env:OLLAMA_PID_FILE -Raw); Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $env:OLLAMA_PID_FILE -Force -ErrorAction SilentlyContinue }"
)

echo.
echo DSH exit code: %RC%
exit /b %RC%

:cleanup_fail
if "%STARTED_OLLAMA%"=="1" (
  echo Stopping temporary Ollama server started by this launcher...
  powershell.exe -NoProfile -Command ^
    "if (Test-Path -LiteralPath $env:OLLAMA_PID_FILE) { $pidValue = [int](Get-Content -LiteralPath $env:OLLAMA_PID_FILE -Raw); Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $env:OLLAMA_PID_FILE -Force -ErrorAction SilentlyContinue }"
)
exit /b 3
