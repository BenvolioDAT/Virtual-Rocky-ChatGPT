@echo off
setlocal
cd /d "%~dp0server"
if not exist ".venv\Scripts\python.exe" (
  echo Create server\.venv and install requirements-virtual.txt. See README.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m brain.virtual --provider chatgpt %*
if errorlevel 1 pause
