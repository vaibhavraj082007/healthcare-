#!/usr/bin/env bash
# ==============================================================================
# RetinaShield — Facility Node Setup & Packaging Script
#
# Configures a local Primary Health Centre (PHC) facility node running:
# 1. FastAPI Application Service
# 2. Local Database & Encrypted Storage
# 3. Next.js Web Interface
# 4. MATLAB Engine / Runtime Worker
#
# IMPORTANT NOTICE:
# RetinaShield is a research and clinical evaluation prototype.
# It is NOT approved for unassisted clinical diagnosis under CDSCO MDR 2017.
# All screenings require qualified ophthalmologist review and sign-off.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "======================================================================"
echo " RetinaShield Facility Node Installation & Setup"
echo " Target Directory: ${REPO_ROOT}"
echo "======================================================================"

# 1. Check Core System Dependencies
echo "[1/6] Checking system prerequisites..."

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required but not installed."; exit 1; }
command -v node >/dev/null 2>&1 || { echo "ERROR: node (v18+) is required but not installed."; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm is required but not installed."; exit 1; }

PYTHON_VER=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "  Found Python: ${PYTHON_VER}"
echo "  Found Node: $(node --version)"
echo "  Found npm: $(npm --version)"

# Check for MATLAB Engine or MCR
MATLAB_AVAILABLE=false
if command -v matlab >/dev/null 2>&1; then
    echo "  Found MATLAB: $(which matlab)"
    MATLAB_AVAILABLE=true
elif [ -n "${MCR_ROOT:-}" ] && [ -d "${MCR_ROOT}" ]; then
    echo "  Found MATLAB Runtime (MCR): ${MCR_ROOT}"
    MATLAB_AVAILABLE=true
else
    echo "  NOTICE: Full MATLAB / MCR not detected in PATH. Classical Python fallback will be configured."
fi

# 2. Setup Local Data & Secure Storage Directories
echo "[2/6] Initializing local storage directories..."
mkdir -p "${REPO_ROOT}/data/images"
mkdir -p "${REPO_ROOT}/data/backups"
mkdir -p "${REPO_ROOT}/data/sync_outbox"
mkdir -p "${REPO_ROOT}/reports/demo_artifacts"
mkdir -p "${REPO_ROOT}/logs"

# Ensure private permissions for image storage (POSIX 0700)
chmod 700 "${REPO_ROOT}/data/images"
chmod 700 "${REPO_ROOT}/data/backups"
echo "  Secured image and backup directories with 0700 permissions."

# 3. Python Virtual Environment & Backend Setup
echo "[3/6] Setting up Python virtual environment..."
cd "${REPO_ROOT}/backend"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  Created virtual environment in backend/venv."
fi

source venv/bin/activate
pip install --upgrade pip setuptools wheel >/dev/null

if [ -f "requirements.txt" ]; then
    echo "  Installing backend dependencies..."
    pip install -r requirements.txt >/dev/null
fi

# Create default .env if not present
if [ ! -f ".env" ]; then
    cat <<EOF > .env
APP_NAME=RetinaShield
APP_ENV=production
DEBUG=false
DATABASE_URL=sqlite+aiosqlite:///${REPO_ROOT}/data/retinashield.db
IMAGE_STORAGE_PATH=${REPO_ROOT}/data/images
BACKUP_STORAGE_PATH=${REPO_ROOT}/data/backups
LOG_LEVEL=INFO
MATLAB_MODE=fallback
ABDM_EXCHANGE_ENABLED=false
ABHA_LINKING_ENABLED=false
MONITORING_SMALL_CELL_THRESHOLD=5
JWT_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
EOF
    echo "  Generated production .env with secure random JWT secret."
fi

# Initialize database schema
echo "  Initializing SQLite database schema..."
python3 -c "import asyncio; from app.db.session import init_db; asyncio.run(init_db())"
echo "  Database schema initialized."

# 4. Frontend Web Interface Setup
echo "[4/6] Setting up frontend application..."
cd "${REPO_ROOT}/frontend"

if [ ! -f ".env.local" ]; then
    cat <<EOF > .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_APP_ENV=production
EOF
    echo "  Created frontend .env.local."
fi

echo "  Installing npm packages..."
npm install --silent >/dev/null 2>&1 || npm install

echo "  Building production Next.js bundle..."
npm run build

# 5. Generate Systemd Service Files (for Linux deployments)
echo "[5/6] Generating system service descriptors..."
SYSTEMD_DIR="${REPO_ROOT}/scripts/systemd"
mkdir -p "${SYSTEMD_DIR}"

cat <<EOF > "${SYSTEMD_DIR}/retinashield-backend.service"
[Unit]
Description=RetinaShield Screening Backend Service
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${REPO_ROOT}/backend
ExecStart=${REPO_ROOT}/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
EnvironmentFile=${REPO_ROOT}/backend/.env

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF > "${SYSTEMD_DIR}/retinashield-frontend.service"
[Unit]
Description=RetinaShield Next.js Web Frontend
After=network.target retinashield-backend.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${REPO_ROOT}/frontend
ExecStart=$(which npm) start -- -p 3000
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF > "${SYSTEMD_DIR}/retinashield-worker.service"
[Unit]
Description=RetinaShield MATLAB Offline Worker
After=network.target retinashield-backend.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${REPO_ROOT}/backend
ExecStart=${REPO_ROOT}/backend/venv/bin/python3 -m app.services.job_queue
Restart=always
RestartSec=10
EnvironmentFile=${REPO_ROOT}/backend/.env

[Install]
WantedBy=multi-user.target
EOF

chmod +x "${SYSTEMD_DIR}"/*.service
echo "  Systemd units written to: ${SYSTEMD_DIR}"

# 6. Verification & Health Check
echo "[6/6] Running system verification..."
cd "${REPO_ROOT}"
python3 "${REPO_ROOT}/scripts/run_engineering_readiness_audit.py"

echo "======================================================================"
echo " RetinaShield Facility Node Setup Complete!"
echo " Web UI:    http://localhost:3000"
echo " API Docs:  http://localhost:8000/docs"
echo " Runbook:   docs/OPERATIONAL_RUNBOOK.md"
echo "======================================================================"
