@echo off
title OpenClaw Startup
echo.
echo ==========================================
echo  OpenClaw - Startup
echo ==========================================
echo.

:: ── 1. Check Ollama ───────────────────────────────────────────────────────────
echo [1/3] Checking Ollama...
curl -s http://localhost:11434 >nul 2>&1
if %errorlevel% neq 0 (
    echo       Ollama not running - starting it...
    start "" "C:\Users\OpenClawAgent\AppData\Local\Programs\Ollama\ollama.exe"
    echo       Waiting for Ollama to load (15 seconds)...
    timeout /t 15 /nobreak >nul
    curl -s http://localhost:11434 >nul 2>&1
    if %errorlevel% neq 0 (
        echo       ERROR: Ollama failed to start. Check that it is installed.
        pause
        exit /b 1
    )
)
echo       Ollama is running.

:: ── 2. Verify model ───────────────────────────────────────────────────────────
echo.
echo [2/3] Checking model (qwen3:8b)...
"C:\Users\OpenClawAgent\Projects\ai-agent\.venv\Scripts\python.exe" -c "import ollama; models = [m['name'] for m in ollama.list()['models']]; exit(0 if any('qwen3:8b' in m for m in models) else 1)" 2>nul
if %errorlevel% neq 0 (
    echo       Model not found - pulling qwen3:8b (this may take a while)...
    ollama pull qwen3:8b
) else (
    echo       qwen3:8b is ready.
)

:: ── 3. Start dashboard ────────────────────────────────────────────────────────
echo.
echo [3/3] Starting dashboard...

:: Kill any existing dashboard on port 8501
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8501" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)

start "" "C:\Users\OpenClawAgent\Projects\ai-agent\.venv\Scripts\streamlit.exe" run "C:\Users\OpenClawAgent\Projects\ai-agent\dashboard.py" --server.port 8501 --server.headless true
timeout /t 3 /nobreak >nul
start "" http://localhost:8501

echo       Dashboard started at http://localhost:8501
echo.
echo ==========================================
echo  All systems ready.
echo  Pipeline runs automatically at 9:00 AM.
echo ==========================================
echo.
