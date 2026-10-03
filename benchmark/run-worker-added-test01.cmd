@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run-worker-qualification-batch.ps1" -CandidatesFile "%SCRIPT_DIR%worker\candidates-added-v1.csv" -OutputRoot "%SCRIPT_DIR%..\local-state\worker-qualification-v1\test-01-added-v1"
exit /b %ERRORLEVEL%
