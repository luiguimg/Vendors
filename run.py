"""Punto de entrada: `python run.py` levanta el portal en http://localhost:8000."""
import os
import sys

import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        app_dir="backend",
    )
