@echo off
setlocal

rem Generic Role Qualification v1 single-run entry point.
rem Usage:
rem   run-role-benchmark-single.cmd <candidate-patch> <runtime-kind> <model-id> <role-prompt> <package> <output-dir> [wall-clock-seconds]

if "%~6"=="" (
  echo Usage:
  echo   %~nx0 ^<candidate-patch^> ^<runtime-kind^> ^<model-id^> ^<role-prompt^> ^<package^> ^<output-dir^> [wall-clock-seconds]
  exit /b 2
)

set "SCRIPT=%~dp0run-role-benchmark-single.ps1"
set "WALL_SECONDS=%~7"
if "%WALL_SECONDS%"=="" set "WALL_SECONDS=600"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" ^
  -CandidatePatch "%~1" ^
  -RuntimeKind "%~2" ^
  -ModelId "%~3" ^
  -RolePrompt "%~4" ^
  -PackageFile "%~5" ^
  -OutputDir "%~6" ^
  -WallSeconds "%WALL_SECONDS%"

exit /b %ERRORLEVEL%
