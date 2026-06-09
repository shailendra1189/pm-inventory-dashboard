@echo off
:: ============================================================
::  PM Inventory Dashboard — Permanent Auto-Start Setup
::  Run this ONCE as Administrator to register all scheduled tasks.
::  After running, the dashboard starts automatically on every
::  Windows boot and data is fetched + alerts sent every day at 9 AM.
:: ============================================================

title PM Dashboard — Auto-Start Setup
color 0A

echo.
echo  =======================================================
echo   PM Inventory Dashboard — Auto-Start Setup
echo  =======================================================
echo.

:: ── Find Python ─────────────────────────────────────────────
for /f "delims=" %%P in ('where python 2^>nul') do (
    set PYTHON_EXE=%%P
    goto :FOUND_PYTHON
)
echo  [ERROR] Python not found in PATH. Please install Python first.
pause
exit /b 1

:FOUND_PYTHON
echo  Python found: %PYTHON_EXE%

:: ── Project directory (where this bat file lives) ────────────
set PROJECT_DIR=%~dp0
:: Remove trailing backslash
if "%PROJECT_DIR:~-1%"=="\" set PROJECT_DIR=%PROJECT_DIR:~0,-1%

echo  Project directory: %PROJECT_DIR%
echo.

:: ── 1. Dashboard auto-start on Windows logon ────────────────
echo  [1/3] Registering dashboard startup task...
schtasks /delete /tn "PM Inventory Dashboard" /f >nul 2>&1
schtasks /create ^
  /tn "PM Inventory Dashboard" ^
  /tr "cmd /c \"%PROJECT_DIR%\Start Dashboard.bat\"" ^
  /sc ONLOGON ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f
if %ERRORLEVEL% NEQ 0 (
    echo  [WARNING] Could not register startup task. Try running as Administrator.
) else (
    echo  [OK] Dashboard will start automatically on Windows logon.
)

:: ── 2. Daily auto-fetch at 9:00 AM ──────────────────────────
echo.
echo  [2/3] Registering daily auto-fetch task (9:00 AM)...
schtasks /delete /tn "PM Dashboard Auto Fetch" /f >nul 2>&1
schtasks /create ^
  /tn "PM Dashboard Auto Fetch" ^
  /tr "\"%PYTHON_EXE%\" \"%PROJECT_DIR%\auto_fetch.py\"" ^
  /sc DAILY ^
  /st 09:00 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /sd 01/01/2024 ^
  /f
if %ERRORLEVEL% NEQ 0 (
    echo  [WARNING] Could not register auto-fetch task. Try running as Administrator.
) else (
    echo  [OK] auto_fetch.py will run daily at 09:00 AM.
    :: Remove battery restriction so task runs on battery-powered laptops too
    powershell -Command "try { $t = Get-ScheduledTask -TaskName 'PM Dashboard Auto Fetch'; $s = $t.Settings; $s.DisallowStartIfOnBatteries = $false; $s.StopIfGoingOnBatteries = $false; Set-ScheduledTask -TaskName 'PM Dashboard Auto Fetch' -Settings $s; Write-Host '  [OK] Battery restriction removed.' } catch { Write-Host '  [INFO] Could not remove battery restriction - do it manually in Task Scheduler.' }"
)

:: ── 3. Start the dashboard right now ─────────────────────────
echo.
echo  [3/3] Starting dashboard now...
start "" "%PROJECT_DIR%\Start Dashboard.bat"
timeout /t 5 /nobreak >nul

:: ── Summary ──────────────────────────────────────────────────
echo.
echo  =======================================================
echo   Setup complete!
echo.
echo   Dashboard: http://localhost:8501
echo   Auto-fetch: runs daily at 09:00 AM
echo   Log file:   %PROJECT_DIR%\data\auto_fetch.log
echo.
echo   To verify tasks:
echo     schtasks /query /tn "PM Inventory Dashboard"
echo     schtasks /query /tn "PM Dashboard Auto Fetch"
echo.
echo   To run auto-fetch manually:
echo     python "%PROJECT_DIR%\auto_fetch.py"
echo  =======================================================
echo.
pause
