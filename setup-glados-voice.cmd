@echo off
setlocal
cd /d "%~dp0server"
if not exist ".venv\Scripts\python.exe" (
  echo Create server\.venv first. See README.
  exit /b 1
)
".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo The project Python environment is broken. Rebuild server\.venv using the README setup steps.
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-glados.txt
if errorlevel 1 (
  echo Could not install sherpa-onnx. Check internet access and Python compatibility.
  exit /b 1
)
".venv\Scripts\python.exe" scripts\setup_glados_voice.py
exit /b %errorlevel%
