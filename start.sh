#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_BUILD=false
DEV=false

for arg in "$@"; do
  case $arg in
    --skip-build) SKIP_BUILD=true ;;
    --dev) DEV=true ;;
  esac
done

echo ""
echo -e "\033[32m==================================\033[0m"
echo -e "\033[32m     NutriAI - Nutrition Tracker  \033[0m"
echo -e "\033[32m==================================\033[0m"
echo ""

# Install Python dependencies. Prefer uv (fast, uses uv.lock); fall back to pip + requirements.txt
# so a machine without uv still starts. PY_RUN becomes the uvicorn launcher used below.
cd "$ROOT/backend"
if command -v uv >/dev/null 2>&1; then
  echo -e "\033[36mInstalling Python dependencies with uv...\033[0m"
  uv sync || { echo -e "\033[31muv sync failed.\033[0m"; exit 1; }
  PY_RUN=(uv run uvicorn)
else
  echo -e "\033[36muv not found - installing Python dependencies with pip...\033[0m"
  pip install -r requirements.txt -q || { echo -e "\033[31mpip install failed. Make sure Python (or uv) is installed.\033[0m"; exit 1; }
  PY_RUN=(python -m uvicorn)
fi

# Install frontend dependencies
echo -e "\033[36mInstalling frontend dependencies...\033[0m"
cd "$ROOT/frontend"
npm install --silent || { echo -e "\033[31mnpm install failed. Make sure Node.js is installed.\033[0m"; exit 1; }

if [ "$DEV" = true ]; then
  # Dev mode: Vite on :8000 (user-facing), FastAPI on :8001 (proxied)
  echo ""
  echo -e "\033[33mStarting in DEV mode (hot reload enabled)...\033[0m"
  echo ""
  echo "  Local:  http://localhost:8000"
  echo ""
  echo "  Mobile: Run 'ipconfig'/'ifconfig' to find your IPv4 address,"
  echo "          then open http://<your-ip>:8000 on your phone."
  echo ""
  echo "  Press Ctrl+C to stop both servers."
  echo ""

  # Start backend on :8001 in background
  cd "$ROOT/backend"
  "${PY_RUN[@]}" main:app --host 0.0.0.0 --port 8001 --reload &
  BACKEND_PID=$!
  echo -e "\033[90mBackend started on :8001 (PID: $BACKEND_PID)\033[0m"

  # Kill backend when this script exits (Ctrl+C or error)
  trap "echo ''; echo 'Stopping backend...'; kill $BACKEND_PID 2>/dev/null; wait $BACKEND_PID 2>/dev/null" EXIT

  # Give backend a moment to bind
  sleep 2

  # Run Vite on :8000 in foreground
  cd "$ROOT/frontend"
  npm run dev

else
  if [ "$SKIP_BUILD" = false ]; then
    echo -e "\033[36mBuilding frontend...\033[0m"
    npm run build || { echo -e "\033[31mFrontend build failed.\033[0m"; exit 1; }
  fi

  cd "$ROOT/backend"

  echo ""
  echo -e "\033[32mServer starting...\033[0m"
  echo ""
  echo "  Local:  http://localhost:8000"
  echo ""
  echo "  Mobile: Run 'ipconfig' to find your IPv4 address,"
  echo "          then open http://<your-ip>:8000 on your phone."
  echo ""
  echo "  Press Ctrl+C to stop."
  echo ""

  "${PY_RUN[@]}" main:app --host 0.0.0.0 --port 8000
fi
