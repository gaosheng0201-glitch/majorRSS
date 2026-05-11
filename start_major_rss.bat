@echo off
echo =========================================
echo    MajorRSS Startup Script
echo =========================================
echo.
echo Activating virtual environment...
call .\.venv\Scripts\activate.bat

echo Starting Background Worker...
start "MajorRSS Worker" cmd /k ".\.venv\Scripts\activate.bat && python worker.py"

echo Starting Streamlit UI...
python -m streamlit run ui\app.py

pause
