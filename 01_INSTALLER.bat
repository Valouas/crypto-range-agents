@echo off
setlocal
cd /d "%~dp0"
py -3.11 --version >nul 2>&1
if not errorlevel 1 (
  py -3.11 -m venv .venv
) else (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
  if errorlevel 1 goto fail
  python -m venv .venv
)
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m range_agents doctor
pause
exit /b 0
:fail
 echo Installation arretee. Python 3.11 ou plus recent et acces PyPI requis.
 pause
 exit /b 1
