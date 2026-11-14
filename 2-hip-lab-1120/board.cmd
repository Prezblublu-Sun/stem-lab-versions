@echo off
rem stem-lab: the dashboard (all experiments, machines, alerts; read only).
rem Run it from any folder, or double-click it. It serves http://127.0.0.1:8791/ on this machine only.
rem Close this window or press Ctrl+C to stop it. Give --no-browser to keep it from opening the browser.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set OPEN=--open
if "%~1"=="--no-browser" set OPEN=
".venv\Scripts\python.exe" -m stemlab.board --port 8791 %OPEN%
if not "%~1"=="--no-browser" pause
