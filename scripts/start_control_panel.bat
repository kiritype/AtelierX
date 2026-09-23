@echo off
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%ROOT%"
rem Opens http://127.0.0.1:8180/ in the default browser once the panel listens (or at once if it is already running).
"%PY%" -B -m atelierx.control --open-browser %*
exit /b %ERRORLEVEL%
