@echo off
rem stem-lab: double-click to open the page in your browser.
rem Closing this window stops the page only; running experiments keep going.
cd /d "%~dp0"
python -m stemlab --open %*
pause
