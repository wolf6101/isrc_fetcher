@echo off
setlocal enabledelayedexpansion
title ISRC Fetcher - Install
color 0B
echo.
echo  ==============================================
echo   ISRC Fetcher - One-time Setup
echo  ==============================================
echo.

REM --- Check Python ---
python --version >nul 2>&1
if !ERRORLEVEL! equ 0 goto :python_found

echo  Python not found. Downloading and installing Python 3.12...
echo.
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe' -OutFile '%TEMP%\python-installer.exe'"
if not exist "%TEMP%\python-installer.exe" goto :download_failed

echo  Installing Python (this takes about a minute)...
"%TEMP%\python-installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
del "%TEMP%\python-installer.exe" >nul 2>&1

REM Refresh PATH so python is found in this session
for /f "usebackq tokens=*" %%p in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('PATH','User')"`) do set "PATH=%%p;%PATH%"

python --version >nul 2>&1
if !ERRORLEVEL! neq 0 goto :python_failed

echo  Python installed successfully.
echo.

:python_found
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  Python found: %PYVER%
echo.

REM --- Install dependencies ---
echo  Installing required packages...
echo.
pip install --quiet openpyxl requests
if !ERRORLEVEL! neq 0 goto :pip_failed
echo.
echo  Packages installed successfully.

REM --- Create desktop shortcut ---
echo.
echo  Creating desktop shortcut...
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\ISRC Fetcher.lnk"
set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%APP_DIR%\Start ISRC Fetcher.bat'; $s.WorkingDirectory = '%APP_DIR%'; $s.Description = 'ISRC Fetcher'; $s.Save()"

if exist "%SHORTCUT_PATH%" (
    echo  Desktop shortcut created: "ISRC Fetcher"
) else (
    echo  (Could not create shortcut - use "Start ISRC Fetcher.bat" directly)
)

echo.
echo  ==============================================
echo   Setup complete!
echo  ==============================================
echo.
echo  To start the app:
echo    - Double-click "ISRC Fetcher" on your Desktop
echo    - OR double-click "Start ISRC Fetcher.bat" here
echo.
pause
exit /b 0

:download_failed
echo  [ERROR] Could not download Python.
echo  Please install it manually from https://www.python.org/downloads/
echo  Then re-run this INSTALL.bat
pause
exit /b 1

:python_failed
echo.
echo  [ERROR] Python installation failed or PATH not updated yet.
echo  Please restart your computer and run INSTALL.bat again.
pause
exit /b 1

:pip_failed
echo.
echo  [ERROR] Package installation failed.
echo  Try running this file as Administrator.
pause
exit /b 1
