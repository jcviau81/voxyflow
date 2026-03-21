#!/bin/bash
# Voxyflow full restart — backend + frontend + proxy
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "🔄 Restarting Voxyflow..."

# Kill existing processes (guard against empty PID)
PID=$(lsof -ti:8000) && [ -n "$PID" ] && kill "$PID"
PID=$(lsof -ti:3000) && [ -n "$PID" ] && kill "$PID"
PID=$(lsof -ti:3457) && [ -n "$PID" ] && kill "$PID"
sleep 2

# Proxy
cd "$SCRIPT_DIR"
nohup node ~/voxyflow-proxy-fork/dist/server/warm-standalone.js 3457 > /tmp/claude-max-api-voxyflow.log 2>&1 &
echo "  Proxy starting (port 3457)..."

# Backend
cd "$SCRIPT_DIR/backend"
nohup venv/bin/uvicorn app.main:app --port 8000 --host 0.0.0.0 >> /tmp/voxyflow-backend.log 2>&1 &
echo "  Backend starting (port 8000)..."

# Frontend
cd "$SCRIPT_DIR/frontend"
nohup npx webpack serve --mode development --port 3000 >> /tmp/voxyflow-frontend.log 2>&1 &
echo "  Frontend starting (port 3000)..."

# Wait and verify
sleep 10
echo ""
echo "=== Status ==="
lsof -ti:3457 >/dev/null 2>&1 && echo "✅ Proxy:    UP" || echo "❌ Proxy:    DOWN"
lsof -ti:8000 >/dev/null 2>&1 && echo "✅ Backend:  UP" || echo "❌ Backend:  DOWN"
lsof -ti:3000 >/dev/null 2>&1 && echo "✅ Frontend: UP" || echo "❌ Frontend: DOWN"
