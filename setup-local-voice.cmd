@echo off
setlocal
cd /d "%~dp0server"
if not exist ".venv\Scripts\python.exe" (
  echo Create server\.venv first. See README.
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements-kokoro.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m spacy download en_core_web_sm
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\setup_kokoro_voice.py
