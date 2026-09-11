@echo off
title TORUS Local Haptic Pad Agent
echo ===================================================
echo   TORUS Doctor Station - Local Haptic Pad Agent
echo ===================================================
echo.
python haptic_pad_agent.py --backend http://127.0.0.1:3000 --secret torus_haptic_sec_2026
pause
