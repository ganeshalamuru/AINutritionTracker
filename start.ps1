param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot

Write-Host ""
Write-Host "==================================" -ForegroundColor Green
Write-Host "     NutriAI - Nutrition Tracker  " -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Green
Write-Host ""

# Copy .env if missing
$envFile = Join-Path $ROOT "backend\.env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $ROOT ".env.example") $envFile
    Write-Host "NOTE: Created backend\.env" -ForegroundColor Yellow
    Write-Host "      You can add your GEMINI_API_KEY there, OR enter it in the app Settings." -ForegroundColor Yellow
    Write-Host ""
}

# Install Python dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
Set-Location (Join-Path $ROOT "backend")
pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed. Make sure Python is installed." -ForegroundColor Red; exit 1 }

# Build frontend (unless skipped)
if (-not $SkipBuild) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    Set-Location (Join-Path $ROOT "frontend")
    npm install --silent
    if ($LASTEXITCODE -ne 0) { Write-Host "npm install failed. Make sure Node.js is installed." -ForegroundColor Red; exit 1 }
    Write-Host "Building frontend..." -ForegroundColor Cyan
    npm run build
    if ($LASTEXITCODE -ne 0) { Write-Host "Frontend build failed." -ForegroundColor Red; exit 1 }
}

# Start server
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

python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
