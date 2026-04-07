#!/bin/bash
echo "Starting Howard Stock Analysis Web App..."

echo "[1/2] Launching Python Backend API (Port 8000)..."
cd /workspaces/HowardStockAnalysis/backend && source ../.venv/bin/activate && python -m uvicorn server:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "[2/2] Launching Nuxt Dashboard (Port 3000)..."
cd /workspaces/HowardStockAnalysis/frontend && NUXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev &
FRONTEND_PID=$!

echo "Both services are booting up in separate processes!"
echo "Once they load, you can access the dashboard at: http://127.0.0.1:3000"
echo "Press Ctrl+C to stop both services."

# Wait for Ctrl+C
trap "echo 'Stopping services...'; kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait