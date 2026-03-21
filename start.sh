#!/bin/sh
# PickAParlay — Start all services
# 1. uvicorn (FastAPI backend) on :8000
# 2. next start (frontend) on :3000
# 3. caddy (reverse proxy) on :8080 (foreground)

set -e

# Ensure data directories exist
mkdir -p "$CACHE_DIR"

echo "[start] Starting PickAParlay..."
echo "[start] Database: $DATABASE_PATH"
echo "[start] Cache: $CACHE_DIR"

# Start FastAPI backend
echo "[start] Starting backend on :8000..."
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1 &
BACKEND_PID=$!

# Start Next.js frontend (standalone mode)
echo "[start] Starting frontend on :3000..."
cd /app/frontend-standalone
PORT=3000 HOSTNAME=0.0.0.0 node server.js &
FRONTEND_PID=$!
cd /app

# Wait for backend to be ready before starting Caddy
echo "[start] Waiting for backend..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/api/credits > /dev/null 2>&1; then
        echo "[start] Backend ready after ${i}s"
        break
    fi
    sleep 1
done

# Wait for frontend to be ready
echo "[start] Waiting for frontend..."
for i in $(seq 1 15); do
    if curl -s http://localhost:3000 > /dev/null 2>&1; then
        echo "[start] Frontend ready after ${i}s"
        break
    fi
    sleep 1
done

# Start Caddy (foreground — keeps container alive)
echo "[start] Starting Caddy proxy on :8080..."
caddy run --config /app/Caddyfile

# If Caddy exits, clean up
kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
