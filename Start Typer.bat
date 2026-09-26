@echo off
cd /d "%~dp0"
python typer_app.py
if errorlevel 1 pause
