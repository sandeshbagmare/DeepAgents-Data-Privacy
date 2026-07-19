@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-demo.ps1"
set "DEMO_EXIT=%ERRORLEVEL%"
if not "%DEMO_EXIT%"=="0" (
  echo.
  echo Demo failed with exit code %DEMO_EXIT%.
  pause
)
exit /b %DEMO_EXIT%