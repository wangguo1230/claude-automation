@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM ── 修复本机拆分/损坏的 Python 安装 ──────────────────────────
REM 本机 C:\Python314 只有解释器缺标准库，标准库在 LOCALAPPDATA，
REM 用 PYTHONHOME 桥接；解释器优先用 C:\Python314\python.exe，回退 py。
set "PYTHONHOME=%LOCALAPPDATA%\Programs\Python\Python314"
if exist "C:\Python314\python.exe" (
    set "PYEXE=C:\Python314\python.exe"
) else (
    set "PYEXE=py"
)

echo [1/3] 检查 Python 依赖...
"%PYEXE%" -m pip install -r backend\requirements.txt -q 2>nul

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

start "claude-backend" cmd /k "cd /d %~dp0 && set PYTHONHOME=%PYTHONHOME% && "%PYEXE%" -m uvicorn backend.main:app --reload --reload-exclude data/* --reload-exclude frontend/* --port 8000"

timeout /t 3 /nobreak >nul

start "claude-frontend" cmd /k "cd /d %~dp0\frontend && npm run dev"

echo 服务已启动（后端和前端各在一个窗口中）
pause
