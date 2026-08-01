@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo [1/3] 检查 Python 依赖...
pip install fastapi uvicorn psycopg2-binary playwright -q 2>nul

if not exist "frontend\node_modules" (
    echo [2/3] 安装前端依赖...
    cd frontend && call npm install && cd ..
) else (
    echo [2/3] 前端依赖已就绪
)

echo [3/3] 启动服务...
echo.
echo ================================
echo   后端: http://localhost:8000
echo   前端: http://localhost:3000
echo   关闭此窗口停止所有服务
echo ================================
echo.

start "claude-backend" cmd /k "cd /d %~dp0 && uvicorn backend.main:app --reload --reload-exclude data/* --reload-exclude frontend/* --port 8000"

timeout /t 3 /nobreak >nul

start "claude-frontend" cmd /k "cd /d %~dp0\frontend && npm run dev"

echo 服务已启动（后端和前端各在一个窗口中）
pause
