@echo off
title TORUS Ultrasound Streamer (Port 8000)
echo ==================================================================
echo  Starting TORUS Ultrasound Video Streamer on Port 8000...
echo  Serving at:
echo    http://127.0.0.1:8000/
echo ==================================================================
python backend\ultrasound.py
pause
