@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo 检查依赖...
pip install fastapi uvicorn psycopg2-binary playwright -q 2>nul

if not exist "frontend\node_modules" (
    echo 安装前端依赖...
    cd frontend && call npm install && cd ..
)

echo.
echo ================================
echo   后端: http://localhost:8000
echo   前端: http://localhost:3000
echo   按 Ctrl+C 停止所有服务
echo ================================
echo.

start "claude-backend" /b cmd /c "uvicorn backend.main:app --reload --reload-exclude data/* --reload-exclude frontend/* --port 8000"
cd frontend
start "claude-frontend" /b cmd /c "npm run dev"
cd ..

echo 服务已启动，按任意键停止...
pause >nul

taskkill /fi "WINDOWTITLE eq claude-backend" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq claude-frontend" /f >nul 2>&1
taskkill /im node.exe /f >nul 2>&1
echo 已停止所有服务
