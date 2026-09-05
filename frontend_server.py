"""
TORUS Clinical Robotics Platform - Unified Server Runner
NOTE: Standalone frontend servers on port 3000 or 3001 have been retired.
All frontend static assets (index.html, app.js, css, assets) and backend APIs
are served from the single official application port 8000 via backend/server.py.
"""

import sys
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

if __name__ == "__main__":
    print("==================================================================")
    print(" [TORUS] Port 8000 is the single official application port.")
    print(" [TORUS] Launching backend/server.py (Frontend + Backend APIs)...")
    print(" [TORUS] Access URL: http://127.0.0.1:8000/index.html")
    print("==================================================================")
    from server import main
    main()
