@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m range_agents collect --task transactions --data data/reel
pause
