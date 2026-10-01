@echo off
setlocal

rem Generic Role Qualification v1 single-run entry point.
rem Usage:
rem   run-role-benchmark-single.cmd <candidate-patch> <runtime-kind> <model-id> <expected-context> <role-prompt> <package> <output-dir> [wall-clock-seconds]

if "%~7"=="" (
  echo Usage:
  echo   %~nx0 ^<candidate-patch^> ^<runtime-kind^> ^<model-id^> ^<expected-context^> ^<role-prompt^> ^<package^> ^<output-dir^> [wall-clock-seconds]
  exit /b 2
)

set "SCRIPT=%~dp0run-role-benchmark-single.ps1"
set "WALL_SECONDS=%~8"
if "%WALL_SECONDS%"=="" set "WALL_SECONDS=600"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" ^
  -CandidatePatch "%~1" ^
  -RuntimeKind "%~2" ^
  -ModelId "%~3" ^
  -ExpectedContextWindow "%~4" ^
  -RolePrompt "%~5" ^
  -PackageFile "%~6" ^
  -OutputDir "%~7" ^
  -WallSeconds "%WALL_SECONDS%"

exit /b %ERRORLEVEL%
