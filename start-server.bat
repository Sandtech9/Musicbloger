@echo off
title Zedhits Central Production Server & CMS
echo ====================================================================
echo   Zedhits Full-Stack Streaming Platform - Live Server
echo ====================================================================
echo.
echo   * Public Web Portal:     http://localhost:8000/
echo   * Admin Control Panel:   http://localhost:8000/admin
echo   * Admin Credentials:     admin / admin123
echo   * Mobile App / LAN Host: http://0.0.0.0:8000/
echo.
echo ====================================================================
python run_server.py
pause
