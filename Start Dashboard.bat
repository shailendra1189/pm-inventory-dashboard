@echo off
title PM Inventory Dashboard
cd /d "%~dp0"
color 0A

:START
cls
echo.
echo  =============================================
echo   PM Inventory Tracking Dashboard
echo   http://localhost:8501
echo  =============================================
echo.
echo  Starting... Keep this window open while using the dashboard.
echo  Close this window to stop the dashboard.
echo.

python -m streamlit run streamlit_app.py ^
    --server.port 8501 ^
    --browser.gatherUsageStats false ^
    --server.headless false

echo.
echo  Dashboard stopped unexpectedly. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto START
