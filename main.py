"""
main.py
───────
Project Root Application Runner.
Delegates to modular backend application at backend/app/main.py.

Usage:
    python main.py
"""

import sys
import os
from pathlib import Path
import uvicorn

# Ensure repository root is in python path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.main import app
from backend.app.core.config import settings

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 STARTING REPRODUCTIVE HEALTH ASSISTANT")
    print(f"📡 Web Interface & API: http://localhost:{settings.PORT}")
    print(f"📖 Swagger Docs:        http://localhost:{settings.PORT}/docs")
    print("=" * 60 + "\n")
    
    uvicorn.run(
        "backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False
    )
