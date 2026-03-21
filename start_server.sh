#!/bin/bash
echo "Starting TRPG Flask server (SD venv)..."
cd "$(dirname "$0")"
/c/git/WebUI/stable-diffusion-webui/venv/Scripts/Python.exe app.py
