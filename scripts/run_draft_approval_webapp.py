#!/usr/bin/env python3
"""
Start the Pantheon V1 draft-approval webapp.

Run from project root. Sets PYTHONPATH so openclaw imports resolve, then
starts the FastAPI server at http://0.0.0.0:8000.

Usage:
    python scripts/run_draft_approval_webapp.py
    python scripts/run_draft_approval_webapp.py --port 8001
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def main():
    parser = argparse.ArgumentParser(description="Start Pantheon draft-approval webapp")
    parser.add_argument("--port", type=int, default=8000, help="Port (default 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default 0.0.0.0)")
    args = parser.parse_args()

    # Run uvicorn with the app from the webapp package (so templates path is correct)
    import uvicorn
    from openclaw.agents.ira.src.webapp.server import app

    print(f"Pantheon draft-approval webapp → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
