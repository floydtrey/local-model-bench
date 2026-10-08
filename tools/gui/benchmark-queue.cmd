@echo off
setlocal
set "QUEUE_REPO=%~dp0..\.."
if exist "%QUEUE_REPO%\.venv\Scripts\python.exe" (
    "%QUEUE_REPO%\.venv\Scripts\python.exe" "%~dp0benchmark-queue.py" %*
) else (
    where py.exe >nul 2>nul
    if errorlevel 1 (
        python.exe "%~dp0benchmark-queue.py" %*
    ) else (
        py.exe -3 "%~dp0benchmark-queue.py" %*
    )
)
set "QUEUE_EXIT=%ERRORLEVEL%"
if not "%QUEUE_EXIT%"=="0" pause
exit /b %QUEUE_EXIT%
