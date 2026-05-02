$ErrorActionPreference = "Continue"
$PROJECT = "C:\Users\OpenClawAgent\Projects\ai-agent"
$PYTHON  = "$PROJECT\.venv\Scripts\python.exe"
$STREAMLIT = "$PROJECT\.venv\Scripts\streamlit.exe"

Write-Host ""
Write-Host "=========================================="
Write-Host " Jarvis - Startup"
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
Write-Host "[2/3] Checking model (gemma3:12b)..."
& $PYTHON -c "import ollama; r = ollama.list(); models = [m.model for m in r.models] if hasattr(r, 'models') else [m['name'] for m in r.get('models', [])]; exit(0 if any('gemma3:12b' in m for m in models) else 1)" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "      Model not found - pulling gemma3:12b (this may take a while)..."
    ollama pull gemma3:12b
} else {
    Write-Host "      gemma3:12b is ready."
}

# --- 3. Start OpenClaw gateway ---
Write-Host ""
Write-Host "[3/4] Starting Jarvis gateway..."
Start-Process "openclaw" -ArgumentList "gateway start" -WindowStyle Hidden
Write-Host "      Jarvis gateway started."

# --- 4. Start dashboard ---
Write-Host ""
Write-Host "[4/4] Starting dashboard (JARVIS Dash)..."

# Kill any existing process on port 8050
$existing = netstat -aon | Select-String ":8050" | ForEach-Object {
    ($_ -split "\s+")[-1]
} | Select-Object -Unique
foreach ($procId in $existing) {
    if ($procId -match "^\d+$") {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

Start-Process $PYTHON -ArgumentList "dash_app.py" -WorkingDirectory $PROJECT -WindowStyle Hidden
Start-Sleep -Seconds 3
Start-Process "http://localhost:8050"

Write-Host "      Dashboard started at http://localhost:8050"
Write-Host ""
Write-Host "=========================================="
Write-Host " All systems ready."
Write-Host " Jarvis gateway running - message it on Discord."
Write-Host " Pipeline runs automatically at 9:00 AM."
Write-Host "=========================================="
Write-Host ""
