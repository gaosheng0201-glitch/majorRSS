@echo off
echo =========================================
echo    MajorRSS Shutdown Script
echo =========================================
echo.
echo Stopping all MajorRSS background processes...

:: Kill processes matching 'streamlit' or 'worker.py'
wmic process where "commandline like '%%streamlit%%' or commandline like '%%worker.py%%'" call terminate >nul 2>&1

echo.
echo All background tasks have been completely terminated!
echo You can now safely close this window.
echo.
pause
