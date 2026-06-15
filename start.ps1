param([switch]$SkipBuild, [switch]$Dev)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot

Write-Host ""
Write-Host "==================================" -ForegroundColor Green
Write-Host "     NutriAI - Nutrition Tracker  " -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Green
Write-Host ""

# Install Python dependencies. Prefer uv (fast, uses uv.lock); fall back to pip + requirements.txt
# so a machine without uv still starts. $pyExe/$pyArgs become the uvicorn launcher below.
Set-Location (Join-Path $ROOT "backend")
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Installing Python dependencies with uv..." -ForegroundColor Cyan
    uv sync
    if ($LASTEXITCODE -ne 0) { Write-Host "uv sync failed." -ForegroundColor Red; exit 1 }
    $pyExe = "uv"; $pyArgs = @("run", "uvicorn")
} else {
    Write-Host "uv not found - installing Python dependencies with pip..." -ForegroundColor Cyan
    pip install -r requirements.txt -q
    if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed. Make sure Python (or uv) is installed." -ForegroundColor Red; exit 1 }
    $pyExe = "python"; $pyArgs = @("-m", "uvicorn")
}

# Install frontend dependencies
Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
Set-Location (Join-Path $ROOT "frontend")
npm install --silent
if ($LASTEXITCODE -ne 0) { Write-Host "npm install failed. Make sure Node.js is installed." -ForegroundColor Red; exit 1 }

if ($Dev) {
    # Dev mode: Vite on :8000 (user-facing), FastAPI on :8001 (proxied)
    Write-Host ""
    Write-Host "Starting in DEV mode (hot reload enabled)..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Local:  http://localhost:8000" -ForegroundColor White
    Write-Host ""
    Write-Host "  Mobile: Run 'ipconfig' to find your IPv4 address," -ForegroundColor White
    Write-Host "          then open http://<your-ip>:8000 on your phone." -ForegroundColor White
    Write-Host ""
    Write-Host "  Press Ctrl+C to stop both servers." -ForegroundColor Gray
    Write-Host ""

    $backendDir = Join-Path $ROOT "backend"
    $backend = Start-Process $pyExe `
        -ArgumentList ($pyArgs + @("main:app", "--host", "0.0.0.0", "--port", "8001", "--reload")) `
        -WorkingDirectory $backendDir `
        -PassThru -NoNewWindow
    Write-Host "Backend started on :8001 (PID: $($backend.Id))" -ForegroundColor DarkGray

    Start-Sleep -Seconds 2

    try {
        Set-Location (Join-Path $ROOT "frontend")
        npm run dev
    } finally {
        Write-Host ""
        Write-Host "Stopping backend..." -ForegroundColor Yellow
        taskkill /F /T /PID $backend.Id 2>$null | Out-Null
    }

} else {
    # Production mode: build then serve via FastAPI
    if (-not $SkipBuild) {
        Write-Host "Building frontend..." -ForegroundColor Cyan
        npm run build
        if ($LASTEXITCODE -ne 0) { Write-Host "Frontend build failed." -ForegroundColor Red; exit 1 }
    }

    Set-Location (Join-Path $ROOT "backend")

    Write-Host ""
    Write-Host "Server starting..." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Local:  http://localhost:8000" -ForegroundColor White
    Write-Host ""
    Write-Host "  Mobile: Run 'ipconfig' to find your IPv4 address," -ForegroundColor White
    Write-Host "          then open http://<your-ip>:8000 on your phone." -ForegroundColor White
    Write-Host ""
    Write-Host "  Press Ctrl+C to stop." -ForegroundColor Gray
    Write-Host ""

    & $pyExe ($pyArgs + @("main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"))
}
