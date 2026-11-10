@echo off
title Cognaut
cd /d "%~dp0"

rem Anaconda installs "python"; the Windows launcher is "py". Try both.
where python >nul 2>&1
if %errorlevel%==0 (
    python code.py
    goto done
)

where py >nul 2>&1
if %errorlevel%==0 (
    py code.py
    goto done
)

echo.
echo   Python was not found on this computer.
echo.
echo   If you have Anaconda, open "Anaconda Prompt" from the Start menu,
echo   type  cd  followed by a space, drag this folder onto the window,
echo   press Enter, then type:   python code.py
echo.
echo   Otherwise install Python from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during setup.
echo.

:done
echo.
pause
