# ============================================================
# Pact Protect — Daily Startup Script
# Run this every time you want to start the app.
# Usage: Right-click -> Run with PowerShell
#        OR in PowerShell: .\start_app.ps1
# ============================================================

$PROJECT_ROOT  = "C:\SEM5\internship"
$BACKEND_DIR   = "$PROJECT_ROOT\backend"
$VENV_ACTIVATE = "$BACKEND_DIR\.venv\Scripts\Activate.ps1"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Pact Protect - Starting App" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# --- Check venv exists ---
if (-not (Test-Path $VENV_ACTIVATE)) {
    Write-Host "[ERROR] Virtual environment not found at:" -ForegroundColor Red
    Write-Host "        $VENV_ACTIVATE" -ForegroundColor Red
    Write-Host ""
    Write-Host "Run the one-time setup first:" -ForegroundColor Yellow
    Write-Host "  cd $BACKEND_DIR" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor Yellow
    Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "  pip install -r requirements.txt" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# --- Check node_modules exists ---
if (-not (Test-Path "$PROJECT_ROOT\node_modules")) {
    Write-Host "[ERROR] node_modules not found." -ForegroundColor Red
    Write-Host "Run 'npm install' in $PROJECT_ROOT first." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[1/2] Starting Backend on http://127.0.0.1:8001 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList `
    "-NoExit", `
    "-Command", `
    "cd '$BACKEND_DIR'; & '$VENV_ACTIVATE'; python run_server.py" `
    -WindowStyle Normal

Write-Host "      Waiting 4 seconds for backend to be ready..." -ForegroundColor DarkGray
Start-Sleep -Seconds 4

Write-Host "[2/2] Starting Frontend on http://localhost:8080 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList `
    "-NoExit", `
    "-Command", `
    "cd '$PROJECT_ROOT'; npm run dev" `
    -WindowStyle Normal

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Both servers are starting!" -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Cyan
Write-Host "  Frontend : http://localhost:8080" -ForegroundColor White
Write-Host "  Backend  : http://127.0.0.1:8001" -ForegroundColor White
Write-Host "  API Docs : http://127.0.0.1:8001/docs" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Open http://localhost:8080 in your browser." -ForegroundColor Yellow
Write-Host "Close the two terminal windows to stop the servers." -ForegroundColor DarkGray
Write-Host ""
Read-Host "Press Enter to close this launcher"
