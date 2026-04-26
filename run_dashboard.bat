@echo off
cd /d "%~dp0"
echo Starting StockDesk at http://127.0.0.1:8000
echo Keep this window open while using the dashboard.
echo.
python app.py
echo.
echo Server stopped. Press any key to close this window.
pause >nul
