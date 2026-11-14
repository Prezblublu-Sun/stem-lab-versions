@echo off
rem stem-lab: the desk web page (one experiment in detail, charts, start and stop).
rem Run it from any folder, or double-click it. It serves http://127.0.0.1:8790/ on this machine only.
rem Close this window or press Ctrl+C to stop it. Give --no-browser to keep it from opening the browser.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set OPEN=--open
if "%~1"=="--no-browser" set OPEN=
".venv\Scripts\python.exe" -m stemlab.desk web --port 8790 %OPEN%
if not "%~1"=="--no-browser" pause
