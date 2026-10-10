@echo off
setlocal
cd /d "%~dp0server"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --console --name VirtualRocky --collect-all sounddevice --collect-all onnxruntime --collect-all faster_whisper --collect-all ctranslate2 --add-data "models;models" virtual_entry.py
if errorlevel 1 exit /b 1
copy .env.example dist\VirtualRocky\.env.example >nul
copy ..\LICENSE dist\VirtualRocky\LICENSE >nul
