@echo off
setlocal

rem Role Qualification v1 smoke launcher.
rem This proves the isolated DSH path only. It does not produce benchmark evidence.

set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "DSH=%APPDATA%\npm\dsh.cmd"
set "BASE_PATCH=%REPO%\benchmark\dsh\role-qualification-v1.patch.yml"
set "MODEL_PATCH=%REPO%\benchmark\dsh\smoke-qwen35-9b.patch.yml"
set "TASK_FILE=%REPO%\benchmark\smoke\planner-path-smoke.txt"
set "DSH_HOME=%REPO%\local-state\role-qualification-v1\dsh-home"
set "DSH_TELEMETRY_DISABLED=1"
set "DSH_PERMISSION_MODE=read-only"
set "ROLE_BENCHMARK_LOCAL_KEY=local-smoke-placeholder"

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

if not exist "%DSH_HOME%" mkdir "%DSH_HOME%" >nul 2>&1

echo.
echo Role Qualification v1 - execution path smoke
echo DSH_HOME: %DSH_HOME%
echo Model: qwen3.5:9b
echo.
echo This run is NOT a benchmark result.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$task = Get-Content -LiteralPath $env:TASK_FILE -Raw; & $env:DSH --profile headless --patch $env:BASE_PATCH --patch $env:MODEL_PATCH $task; exit $LASTEXITCODE"

set "RC=%ERRORLEVEL%"
echo.
echo DSH exit code: %RC%
exit /b %RC%
