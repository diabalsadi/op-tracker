@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 server.py --open
goto finished
:usepython
python server.py --open
:finished
if errorlevel 1 pause
