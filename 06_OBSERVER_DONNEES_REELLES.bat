@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m range_agents observe --config configs/observation.json --data data/reel --out runs/observation
pause
