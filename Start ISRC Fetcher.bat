@echo off
title ISRC Fetcher
cd /d "%~dp0"
python app.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo  Something went wrong. Did you run INSTALL.bat first?
    pause
)
