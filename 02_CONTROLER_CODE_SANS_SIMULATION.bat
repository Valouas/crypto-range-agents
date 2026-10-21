@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto fail
.venv\Scripts\python.exe scripts\validate_static.py
set RET=%ERRORLEVEL%
pause
exit /b %RET%
:fail
 echo Lancez d'abord 01_INSTALLER.bat.
 pause
 exit /b 1
