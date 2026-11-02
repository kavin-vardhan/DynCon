@echo off
rem Start-Demo.bat - double-click this. Desk mode by default; pass -Booth for the booth.
rem
rem It is a wrapper and nothing else: everything is in Start-Demo.ps1 next to it. The
rem -ExecutionPolicy Bypass is what lets that script run on a machine where PowerShell
rem scripts are otherwise blocked, which is most machines nobody has set up.
rem
rem Set DC_NO_PAUSE=1 to stop it waiting for a key press when something goes wrong, which
rem is what an automated run wants and a person double-clicking does not.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Demo.ps1" %*
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" if not defined DC_NO_PAUSE (
  echo.
  echo The demo did not start. The message above says why.
  echo Press any key to close this window.
  pause >nul
)
exit /b %EXITCODE%
