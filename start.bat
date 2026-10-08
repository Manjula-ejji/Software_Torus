@echo off
title TORUS Platform Unified Server
echo ==================================================================
echo  Starting TORUS Platform Unified Server on Port 5000...
echo  Serving Frontend + Backend APIs at:
echo    http://127.0.0.1:5000/
echo ==================================================================
python backend\server.py
pause
