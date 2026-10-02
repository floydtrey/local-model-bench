@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-worker-qualification-batch.ps1" %*
