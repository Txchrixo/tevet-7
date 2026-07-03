#!/bin/bash
# run.sh — convenience launcher for the Tevet-7 agentic service.
# Starts uvicorn on port 8001 (the port the Next.js prototype expects via
# the Caddy gateway's XTransformPort=8001).
cd /home/z/my-project/agentic-service
exec /home/z/.venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
