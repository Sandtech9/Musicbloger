@echo off
title Zedhits Central FastAPI Engine & Dynamic CMS
echo ====================================================================
echo   Starting Zedhits Central FastAPI Engine & Dynamic CMS
echo ====================================================================
echo.
echo   Public Web Portal:     http://localhost:8000/
echo   Admin Control Panel:   http://localhost:8000/admin
echo   Default Credentials:   admin / admin123
echo   Android / LAN URL:     http://192.168.1.119:8000/
echo.
echo ====================================================================
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
pause
