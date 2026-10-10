@echo off
setlocal
cd /d "%~dp0server"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --console --name VirtualRocky --collect-all sounddevice --collect-all onnxruntime --collect-all faster_whisper --collect-all ctranslate2 --add-data "models;models" virtual_entry.py
if errorlevel 1 exit /b 1
xcopy /E /I /Y personalities dist\VirtualRocky\personalities >nul
xcopy /E /I /Y voices dist\VirtualRocky\voices >nul
xcopy /E /I /Y face_themes dist\VirtualRocky\face_themes >nul
copy .env.example dist\VirtualRocky\.env.example >nul
copy ..\LICENSE dist\VirtualRocky\LICENSE >nul
