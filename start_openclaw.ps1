$ErrorActionPreference = "Continue"
$PROJECT = "C:\Users\OpenClawAgent\Projects\ai-agent"
$PYTHON  = "$PROJECT\.venv\Scripts\python.exe"
$STREAMLIT = "$PROJECT\.venv\Scripts\streamlit.exe"

Write-Host ""
Write-Host "=========================================="
Write-Host " OpenClaw - Startup"
Write-Host "=========================================="
Write-Host ""

# --- 1. Check Ollama ---
Write-Host "[1/3] Checking Ollama..."
try {
    $response = Invoke-WebRequest -Uri "http://localhost:11434" -UseBasicParsing -TimeoutSec 3
    Write-Host "      Ollama is running."
} catch {
    Write-Host "      Ollama not running - starting it..."
    $ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path $ollamaExe) {
        Start-Process $ollamaExe
        Write-Host "      Waiting for Ollama to load (15 seconds)..."
        Start-Sleep -Seconds 15
        try {
            Invoke-WebRequest -Uri "http://localhost:11434" -UseBasicParsing -TimeoutSec 3 | Out-Null
            Write-Host "      Ollama is running."
        } catch {
            Write-Host "      ERROR: Ollama failed to start. Open it manually and re-run."
            Read-Host "Press Enter to exit"
            exit 1
        }
    } else {
        Write-Host "      ERROR: Ollama not found at $ollamaExe"
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# --- 2. Verify model ---
Write-Host ""
Write-Host "[2/3] Checking model (qwen3:8b)..."
& $PYTHON -c "import ollama; r = ollama.list(); models = [m.model for m in r.models] if hasattr(r, 'models') else [m['name'] for m in r.get('models', [])]; exit(0 if any('qwen3:8b' in m for m in models) else 1)" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "      Model not found - pulling qwen3:8b (this may take a while)..."
    ollama pull qwen3:8b
} else {
    Write-Host "      qwen3:8b is ready."
}

# --- 3. Start dashboard ---
Write-Host ""
Write-Host "[3/3] Starting dashboard..."

# Kill any existing Streamlit on port 8501
$existing = netstat -aon | Select-String ":8501" | ForEach-Object {
    ($_ -split "\s+")[-1]
} | Select-Object -Unique
foreach ($procId in $existing) {
    if ($procId -match "^\d+$") {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

Start-Process $STREAMLIT -ArgumentList "run `"$PROJECT\dashboard.py`" --server.port 8501 --server.headless true" -WorkingDirectory $PROJECT
Start-Sleep -Seconds 3
Start-Process "http://localhost:8501"

Write-Host "      Dashboard started at http://localhost:8501"
Write-Host ""
Write-Host "=========================================="
Write-Host " All systems ready."
Write-Host " Pipeline runs automatically at 9:00 AM."
Write-Host "=========================================="
Write-Host ""
