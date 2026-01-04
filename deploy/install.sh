#!/usr/bin/env bash
#
# Penny Deployment Script
# Deploys Penny to OCI Dev (100.126.13.70) via Tailscale
#
# Usage: ./deploy/install.sh [--full|--update|--restart]
#   --full    Full install (rsync + venv + systemd)
#   --update  Update code only (rsync + restart)
#   --restart Just restart the service
#

set -euo pipefail

# Configuration
REMOTE_HOST="${PENNY_REMOTE_HOST:-100.126.13.70}"
REMOTE_USER="${PENNY_REMOTE_USER:-ubuntu}"
REMOTE_PATH="${PENNY_REMOTE_PATH:-/home/ubuntu/penny}"
LOCAL_PATH="$(cd "$(dirname "$0")/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[PENNY]${NC} $1"; }
warn() { echo -e "${YELLOW}[PENNY]${NC} $1"; }
error() { echo -e "${RED}[PENNY]${NC} $1" >&2; }

# Parse arguments
MODE="${1:---update}"

case "$MODE" in
    --full|--update|--restart)
        ;;
    *)
        echo "Usage: $0 [--full|--update|--restart]"
        exit 1
        ;;
esac

log "Deploying Penny to ${REMOTE_USER}@${REMOTE_HOST}"
log "Mode: ${MODE}"

# Test SSH connection
if ! ssh -o ConnectTimeout=5 "${REMOTE_USER}@${REMOTE_HOST}" "echo 'SSH OK'" &>/dev/null; then
    error "Cannot connect to ${REMOTE_HOST}. Is Tailscale running?"
    exit 1
fi

# Sync code
if [[ "$MODE" != "--restart" ]]; then
    log "Syncing code..."
    rsync -avz --delete \
        --exclude '.venv' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude '.git' \
        --exclude 'data/' \
        --exclude '.env' \
        --exclude 'secrets/' \
        --exclude '.pytest_cache' \
        "${LOCAL_PATH}/" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/"
    log "Code synced"
fi

# Full install
if [[ "$MODE" == "--full" ]]; then
    log "Running full install..."

    ssh "${REMOTE_USER}@${REMOTE_HOST}" bash << 'REMOTE_SCRIPT'
set -euo pipefail

cd /home/ubuntu/penny

# Create data directory
mkdir -p data
chmod 755 data

# Create virtual environment
if [[ ! -d venv ]]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate and install
source venv/bin/activate
pip install --upgrade pip
pip install -e .

# Check for .env file
if [[ ! -f .env ]]; then
    echo "WARNING: No .env file found. Copy .env.example and configure."
fi

# Install systemd service
if [[ -f deploy/penny.service ]]; then
    sudo cp deploy/penny.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable penny
    echo "Systemd service installed"
fi

echo "Full install complete"
REMOTE_SCRIPT
fi

# Restart service
log "Restarting penny service..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl restart penny || sudo systemctl start penny"

# Check status
log "Checking service status..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl status penny --no-pager" || true

# Health check
sleep 2
log "Running health check..."
if ssh "${REMOTE_USER}@${REMOTE_HOST}" "curl -sf http://localhost:8000/health" &>/dev/null; then
    log "Health check passed!"
else
    warn "Health check failed - service may still be starting"
fi

log "Deployment complete!"
echo ""
log "Service URL: http://${REMOTE_HOST}:8000"
log "Logs: ssh ${REMOTE_USER}@${REMOTE_HOST} 'journalctl -u penny -f'"
