#!/bin/bash
cd "$(dirname "$0")"

# 安装后端依赖
pip install fastapi uvicorn -q 2>/dev/null

# 安装前端依赖（如果没装过）
if [ ! -d "frontend/node_modules" ]; then
  echo "安装前端依赖..."
  cd frontend && npm install && cd ..
fi

# 启动后端
echo "启动后端 http://localhost:8000 ..."
uvicorn backend.main:app --reload --reload-exclude "data/*" --reload-exclude "frontend/*" --port 8000 &
BACKEND_PID=$!

# 启动前端
echo "启动前端 http://localhost:3000 ..."
cd frontend && npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "================================"
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:3000"
echo "  按 Ctrl+C 停止所有服务"
echo "================================"
echo ""

cleanup() {
  echo "停止服务..."
  kill $BACKEND_PID 2>/dev/null
  kill $FRONTEND_PID 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

wait
