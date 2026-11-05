@echo off
cd /d "%~dp0"
python -c "import webview, edge_tts, MetaTrader5, segno, psutil, PIL" 2>nul || (
  echo Installing Jarvis components...
  python -m pip install pywebview edge-tts MetaTrader5 segno psutil pillow || (pause & exit /b)
)
rem Voice control is optional: if it can't install, Jarvis still starts without it
python -c "import openwakeword, faster_whisper, sounddevice" 2>nul || (
  echo Installing voice control, this can take a few minutes the first time...
  python -m pip install openwakeword faster-whisper sounddevice
)
python -c "import vidaa" 2>nul || python -m pip install vidaa-control
start "" pythonw server.py
