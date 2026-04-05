#!/bin/bash
echo "DealFlowTracker — Starting..."
cd "$(dirname "$0")/backend"
python -m app.seed 2>/dev/null
echo "Starting backend on :8006..."
uvicorn app.main:app --port 8006 --host 0.0.0.0 --reload &
BACKEND_PID=$!
cd "$(dirname "$0")/frontend"
echo "Starting frontend on :5178..."
npm run dev &
FRONTEND_PID=$!
echo ""
echo "DealFlowTracker running:"
echo "  Backend:  http://localhost:8006"
echo "  Frontend: http://localhost:5178"
echo "  Demo: demo@dealflow.dev / demo123"
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
