#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_BUILD=false

for arg in "$@"; do
  case $arg in
    --skip-build) SKIP_BUILD=true ;;
  esac
done

echo ""
echo -e "\033[32m==================================\033[0m"
echo -e "\033[32m     NutriAI - Nutrition Tracker  \033[0m"
echo -e "\033[32m==================================\033[0m"
echo ""

# Install Python dependencies
echo -e "\033[36mInstalling Python dependencies...\033[0m"
cd "$ROOT/backend"
pip install -r requirements.txt -q || { echo -e "\033[31mpip install failed. Make sure Python is installed.\033[0m"; exit 1; }

# Build frontend (unless skipped)
if [ "$SKIP_BUILD" = false ]; then
  echo -e "\033[36mInstalling frontend dependencies...\033[0m"
  cd "$ROOT/frontend"
  npm install --silent || { echo -e "\033[31mnpm install failed. Make sure Node.js is installed.\033[0m"; exit 1; }
  echo -e "\033[36mBuilding frontend...\033[0m"
  npm run build || { echo -e "\033[31mFrontend build failed.\033[0m"; exit 1; }
fi

# Start server
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

python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
