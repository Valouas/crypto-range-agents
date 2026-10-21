@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m range_agents collect --task structures --data data/reel
pause
