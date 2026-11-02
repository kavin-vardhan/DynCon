@echo off
rem Stop-Demo.bat - double-click this to stop everything Start-Demo.bat started.
rem
rem Pass -Any to also stop a game or a server that was started some other way.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop-Demo.ps1" %*
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo Something is still running. The message above says what.
  echo Press any key to close this window.
  pause >nul
)
exit /b %EXITCODE%
