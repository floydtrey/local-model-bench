@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-dsh-ollama-multitool-preflight.ps1" %*
