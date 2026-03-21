@echo off
echo Starting TRPG Flask server (SD venv)...
cd /d %~dp0
C:\git\WebUI\stable-diffusion-webui\venv\Scripts\Python.exe app.py
pause
