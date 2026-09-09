#!/bin/bash
# =============================================================================
# RetinaShield — Development Environment Setup
# =============================================================================
# Usage: ./scripts/setup_dev.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================================"
echo " RetinaShield — Development Setup"
echo " RESEARCH SCREENING PROTOTYPE"
echo "============================================================"
echo ""

# Check prerequisites
echo "▸ Checking prerequisites..."

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found. Install Python 3.11+."; exit 1; }
command -v node >/dev/null 2>&1 || { echo "ERROR: node not found. Install Node.js 18+."; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm not found. Install npm."; exit 1; }

echo "  ✓ Python $(python3 --version 2>&1 | awk '{print $2}')"
echo "  ✓ Node.js $(node --version)"
echo "  ✓ npm $(npm --version)"

# Check MATLAB
if command -v matlab >/dev/null 2>&1; then
    echo "  ✓ MATLAB found"
else
    echo "  ⚠ MATLAB not found — will use Python fallback mode"
fi

# Check PostgreSQL
if command -v psql >/dev/null 2>&1; then
    echo "  ✓ PostgreSQL found"
else
    echo "  ⚠ PostgreSQL not found — install with: brew install postgresql@16"
    echo "    Or use Docker: docker compose up -d postgres"
fi

echo ""

# --- Backend Setup ---
echo "▸ Setting up Python backend..."
cd "$PROJECT_DIR/backend"

# Create virtual environment
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  ✓ Virtual environment created"
fi

# Activate and install dependencies
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  ✓ Python dependencies installed"

# Create .env from template
cd "$PROJECT_DIR"
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  ✓ Created .env from template — EDIT WITH YOUR VALUES"
fi

# Create data directories
mkdir -p data/images data/analysis
echo "  ✓ Data directories created"

echo ""

# --- Frontend Setup ---
echo "▸ Setting up Next.js frontend..."
cd "$PROJECT_DIR/frontend"

if [ ! -d "node_modules" ]; then
    npm install
fi
echo "  ✓ Frontend dependencies installed"

echo ""

# --- MATLAB Setup ---
echo "▸ MATLAB pipeline..."
if command -v matlab >/dev/null 2>&1; then
    echo "  ✓ MATLAB available — running tests..."
    matlab -batch "addpath('$PROJECT_DIR/matlab/src'); cd('$PROJECT_DIR/matlab/tests'); runtests('test_pipeline')" || true
else
    echo "  ⚠ MATLAB not installed — skipping tests"
    echo "  ⚠ Set MATLAB_MODE=fallback in .env"
fi

echo ""
echo "============================================================"
echo " Setup Complete!"
echo "============================================================"
echo ""
echo " To start the development servers:"
echo ""
echo "   Backend:  cd backend && source venv/bin/activate && uvicorn app.main:app --reload"
echo "   Frontend: cd frontend && npm run dev"
echo ""
echo " API docs:   http://localhost:8000/docs"
echo " Frontend:   http://localhost:3000"
echo ""
echo " ⚠ RESEARCH SCREENING PROTOTYPE — not for clinical use"
echo "============================================================"
