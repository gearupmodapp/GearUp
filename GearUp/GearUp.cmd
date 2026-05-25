@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

if exist "%SCRIPT_DIR%GearUp.exe" (
    "%SCRIPT_DIR%GearUp.exe"
    exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py "%SCRIPT_DIR%gearup_gui.py"
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python "%SCRIPT_DIR%gearup_gui.py"
    exit /b %ERRORLEVEL%
)

echo ERROR: Python interpreter not found and GearUp.exe missing.
exit /b 1
