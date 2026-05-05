@echo off
title Isaac Sim Launcher
cd /d "%~dp0"
python isaac_sim_launcher.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to launch. Make sure Python and paramiko are installed.
    echo   1. Install Python:  scoop install python  OR  https://python.org
    echo   2. Install paramiko: pip install paramiko
    echo.
    pause
)
