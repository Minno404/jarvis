@echo off
cd /d "%~dp0"
rem Started by Windows at log-on: skip the component checks (they were done when Jarvis was installed) so he's up first
if /i "%~1"=="--startup" goto launch
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
python -c "import pystray" 2>nul || python -m pip install pystray
python -c "import pycaw" 2>nul || python -m pip install pycaw
python -c "import pypdf" 2>nul || python -m pip install pypdf
python -c "import openpyxl" 2>nul || python -m pip install openpyxl
:launch
rem Jarvis.exe shows as "Jarvis" with his icon in Task Manager and the taskbar (falls back to pythonw)
set "JEXE=pythonw"
for /f "delims=" %%e in ('python appexe.py') do set "%%e"
start "" "%JEXE%" server.py %*
