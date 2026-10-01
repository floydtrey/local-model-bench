@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-planner-batch.ps1" %*
