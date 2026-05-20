#!/bin/sh
# PickAParlay — Start all services
# 1. uvicorn (FastAPI backend) on :8000  — watched by backend_watchdog
# 2. next start (frontend) on :3000
# 3. caddy (reverse proxy) on :8080 (foreground — keeps container alive)

set -e

# Ensure data directories exist
mkdir -p "$CACHE_DIR"

echo "[start] Starting PickAParlay..."
echo "[start] Database: $DATABASE_PATH"
echo "[start] Cache: $CACHE_DIR"

# ---------------------------------------------------------------------------
# Backend watchdog — restarts uvicorn if it crashes.
# After 5 failed attempts it kills the container so Fly.io can restart it
# cleanly (the /health check will fail, triggering Fly.io's auto-restart).
# ---------------------------------------------------------------------------

start_backend() {
  uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1 &
  echo $!
}

backend_watchdog() {
  local attempts=0
  local pid
  pid=$(start_backend)
  echo "[start] Backend started (pid $pid)"
  while true; do
    sleep 5
    if ! kill -0 "$pid" 2>/dev/null; then
      attempts=$((attempts + 1))
      echo "[watchdog] Backend process died (attempt $attempts/5) — restarting..."
      if [ "$attempts" -ge 5 ]; then
        echo "[watchdog] Backend unrecoverable after 5 attempts — killing container so Fly.io can restart"
        # Kill our own process group — Caddy exits, Fly.io detects health check failure, restarts machine
        kill 0
        exit 1
      fi
      sleep 3
      pid=$(start_backend)
      echo "[watchdog] Backend restarted (pid $pid)"
    fi
  done
}

# Start watchdog in background (it starts the backend internally)
backend_watchdog &
WATCHDOG_PID=$!

# Start Next.js frontend (standalone mode)
echo "[start] Starting frontend on :3000..."
cd /app/frontend-standalone
PORT=3000 HOSTNAME=0.0.0.0 node server.js &
FRONTEND_PID=$!
cd /app

# Wait for backend to be ready before starting Caddy
echo "[start] Waiting for backend..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
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

# If Caddy exits, clean up everything
kill $WATCHDOG_PID $FRONTEND_PID 2>/dev/null
