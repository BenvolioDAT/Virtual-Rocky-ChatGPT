@echo off
setlocal
cd /d "%~dp0server"
if not exist ".venv\Scripts\python.exe" (
  echo Create server\.venv and install requirements-screen.txt. See docs\screen-vision.md.
  pause
  exit /b 1
)
echo Running the Screen Vision diagnostic. Normal use: right-click Rocky and choose Enable Screen Vision.
".venv\Scripts\python.exe" -m desktop_vision.test_capture
if errorlevel 1 pause
