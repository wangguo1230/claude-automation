#!/bin/bash
cd "$(dirname "$0")"

# ── 修复本机拆分/损坏的 Python 安装 ──────────────────────────
# C:\Python314 只有解释器缺标准库，标准库在 LOCALAPPDATA，用 PYTHONHOME 桥接。
export PYTHONHOME="${PYTHONHOME:-C:/Users/$USERNAME/AppData/Local/Programs/Python/Python314}"
if [ -x "/c/Python314/python.exe" ]; then
  PY="/c/Python314/python.exe"
elif command -v py >/dev/null 2>&1; then
  PY="py"
else
  PY="python"
fi

# 安装后端依赖
echo "检查 Python 依赖..."
"$PY" -m pip install -r backend/requirements.txt -q 2>/dev/null

# 安装前端依赖（如果没装过）
if [ ! -d "frontend/node_modules" ]; then
  echo "安装前端依赖..."
  cd frontend && npm install && cd ..
fi

# 启动后端
echo "启动后端 http://localhost:8000 ..."
"$PY" -m uvicorn backend.main:app --reload --reload-exclude "data/*" --reload-exclude "frontend/*" --port 8000 &
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
