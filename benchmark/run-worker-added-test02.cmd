@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run-worker-intent04-batch.ps1" -CandidatesFile "%SCRIPT_DIR%worker\candidates-added-test02-v1.csv" -OutputRoot "%SCRIPT_DIR%..\local-state\worker-qualification-v1\test-02-intent04-added-v1"
exit /b %ERRORLEVEL%
