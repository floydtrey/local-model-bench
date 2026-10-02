@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-worker-intent04-batch.ps1" -CandidatesFile "%~dp0worker\candidates-test02-smoke.csv" -OutputRoot "%~dp0..\local-state\worker-qualification-v1\test-02-intent04-smoke-qwen38-v3" %*
