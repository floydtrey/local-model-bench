@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-planner-batch.ps1" -CandidatesFile "%~dp0planner\candidates-reasoning-on.csv" -IntentIds intent-06 -OutputRoot "%~dp0..\local-state\role-qualification-v1\planner-intent06-reasoning-v1" %*
