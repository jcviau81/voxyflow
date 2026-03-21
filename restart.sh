#!/bin/bash
# Voxyflow full restart — backend + frontend + proxy
echo "🔄 Restarting Voxyflow..."

# Kill existing processes
kill $(lsof -ti:8000) 2>/dev/null
kill $(lsof -ti:3000) 2>/dev/null
kill $(lsof -ti:3457) 2>/dev/null
sleep 2

# Proxy
cd ~/voxyflow
nohup node ~/voxyflow-proxy-fork/dist/server/warm-standalone.js 3457 > /tmp/claude-max-api-voxyflow.log 2>&1 &
echo "  Proxy starting (port 3457)..."

# Backend
cd ~/voxyflow/backend
nohup venv/bin/uvicorn app.main:app --port 8000 --host 0.0.0.0 >> /tmp/voxyflow-backend.log 2>&1 &
echo "  Backend starting (port 8000)..."

# Frontend
cd ~/voxyflow/frontend
nohup npx webpack serve --mode development --port 3000 >> /tmp/voxyflow-frontend.log 2>&1 &
echo "  Frontend starting (port 3000)..."

# Wait and verify
sleep 10
echo ""
echo "=== Status ==="
lsof -ti:3457 >/dev/null 2>&1 && echo "✅ Proxy:    UP" || echo "❌ Proxy:    DOWN"
lsof -ti:8000 >/dev/null 2>&1 && echo "✅ Backend:  UP" || echo "❌ Backend:  DOWN"
lsof -ti:3000 >/dev/null 2>&1 && echo "✅ Frontend: UP" || echo "❌ Frontend: DOWN"
