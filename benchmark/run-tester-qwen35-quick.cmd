@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run-tester-qwen35-quick.ps1"
exit /b %ERRORLEVEL%
