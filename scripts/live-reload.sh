#!/usr/bin/env bash
# Live reload: watch for file changes and sync to Steam Deck automatically.
# Usage: ./scripts/live-reload.sh [--backend-only | --frontend-only]
#
# Requires: fswatch (brew install fswatch), SSH key auth to Steam Deck.
# Configuration via environment variables or .env.deck file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Configuration ---
# Override via environment or .env.deck in repo root
ENV_FILE="$REPO_DIR/.env.deck"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
fi

DECK_HOST="${DECK_HOST:-192.168.0.199}"
DECK_USER="${DECK_USER:-deck}"
DECK_PLUGIN_DIR="${DECK_PLUGIN_DIR:-/home/deck/homebrew/plugins/deck-controller}"
DECK_DEPLOY_TMP="/tmp/deck-controller-deploy"
SSH_OPTS="${SSH_OPTS:--o ConnectTimeout=5 -o BatchMode=yes}"
DECK_PASS="${DECK_PASS:-}"

# Helper: run SSH command, using sshpass if DECK_PASS is set
_ssh() {
  if [[ -n "$DECK_PASS" ]]; then
    sshpass -p "$DECK_PASS" ssh $SSH_OPTS "$@"
  else
    ssh $SSH_OPTS "$@"
  fi
}

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# --- Mode ---
MODE="all"  # all | backend | frontend
DEPLOY_ONLY=false
case "${1:-}" in
  --backend-only)    MODE="backend" ;;
  --frontend-only)   MODE="frontend" ;;
  --deploy-only)     DEPLOY_ONLY=true ;;
  --deploy-backend)  MODE="backend";  DEPLOY_ONLY=true ;;
  --deploy-frontend) MODE="frontend"; DEPLOY_ONLY=true ;;
  --help|-h)
    echo "Usage: $0 [--backend-only | --frontend-only | --deploy-backend | --deploy-frontend | --deploy-only]"
    echo ""
    echo "  --deploy-backend   Sync backend + restart, then exit (no watcher)"
    echo "  --deploy-frontend  Build frontend + sync + restart, then exit (no watcher)"
    echo "  --deploy-only      Sync all + restart, then exit (no watcher)"
    echo ""
    echo "Environment variables (or set in .env.deck):"
    echo "  DECK_HOST       Steam Deck IP (default: 192.168.0.199)"
    echo "  DECK_USER       SSH user (default: deck)"
    echo "  DECK_PLUGIN_DIR Plugin path on Deck (default: /home/deck/homebrew/plugins/deck-controller)"
    echo "  DECK_PASS       Sudo password for deck user"
    exit 0
    ;;
esac

# --- Preflight checks ---
if ! command -v fswatch &>/dev/null; then
  echo -e "${RED}✗ fswatch not found. Install: brew install fswatch${NC}"
  exit 1
fi

echo -e "${CYAN}▸ Testing SSH connection to ${DECK_USER}@${DECK_HOST}...${NC}"
# shellcheck disable=SC2086
if ! _ssh "${DECK_USER}@${DECK_HOST}" echo "ok" &>/dev/null; then
  echo -e "${RED}✗ Cannot connect to ${DECK_USER}@${DECK_HOST}${NC}"
  echo "  Make sure Steam Deck is awake and SSH is running:"
  echo "    sudo systemctl start sshd"
  exit 1
fi
echo -e "${GREEN}✓ SSH connection OK${NC}"

# Ensure temp deploy directory exists on Deck
# shellcheck disable=SC2086
_ssh "${DECK_USER}@${DECK_HOST}" "mkdir -p ${DECK_DEPLOY_TMP}/{backend,defaults,assets,dist}"

# --- Sync functions ---
# DeckyLoader takes root ownership of plugin files, so we rsync to /tmp first,
# then sudo cp into the plugin directory.
sync_backend() {
  echo -e "${YELLOW}↑ Syncing backend...${NC}"
  local DST="${DECK_USER}@${DECK_HOST}:${DECK_DEPLOY_TMP}"
  local RSYNC_SSH="ssh $SSH_OPTS"
  [[ -n "$DECK_PASS" ]] && RSYNC_SSH="sshpass -p '$DECK_PASS' ssh $SSH_OPTS"
  rsync -az --delete \
    -e "$RSYNC_SSH" \
    "$REPO_DIR/main.py" "$REPO_DIR/plugin.json" "$REPO_DIR/package.json" \
    "$DST/"
  rsync -az --delete \
    -e "$RSYNC_SSH" \
    "$REPO_DIR/backend/" \
    "$DST/backend/"
  rsync -az --delete \
    -e "$RSYNC_SSH" \
    "$REPO_DIR/defaults/" \
    "$DST/defaults/"
  rsync -az --delete \
    -e "$RSYNC_SSH" \
    "$REPO_DIR/assets/" \
    "$DST/assets/"
  _ssh "${DECK_USER}@${DECK_HOST}" "sudo -n /usr/bin/bash -c 'cp -rf ${DECK_DEPLOY_TMP}/* ${DECK_PLUGIN_DIR}/'"
  echo -e "${GREEN}✓ Backend synced${NC}"
}

sync_frontend() {
  echo -e "${YELLOW}↑ Building frontend...${NC}"
  (cd "$REPO_DIR" && pnpm run build --silent 2>&1) || {
    echo -e "${RED}✗ Frontend build failed${NC}"
    return 1
  }
  echo -e "${YELLOW}↑ Syncing frontend dist/...${NC}"
  # shellcheck disable=SC2086
  local RSYNC_SSH="ssh $SSH_OPTS"
  [[ -n "$DECK_PASS" ]] && RSYNC_SSH="sshpass -p '$DECK_PASS' ssh $SSH_OPTS"
  rsync -az --delete \
    -e "$RSYNC_SSH" \
    "$REPO_DIR/dist/" \
    "${DECK_USER}@${DECK_HOST}:${DECK_DEPLOY_TMP}/dist/"
  _ssh "${DECK_USER}@${DECK_HOST}" "sudo -n /usr/bin/bash -c 'cp -rf ${DECK_DEPLOY_TMP}/dist/* ${DECK_PLUGIN_DIR}/dist/'"
  echo -e "${GREEN}✓ Frontend synced${NC}"
}

restart_plugin() {
  echo -e "${YELLOW}↻ Restarting DeckyLoader...${NC}"
  # shellcheck disable=SC2086
  _ssh "${DECK_USER}@${DECK_HOST}" "sudo -n /usr/bin/systemctl restart plugin_loader" 2>/dev/null || {
    echo -e "${RED}✗ Failed to restart plugin_loader (may need NOPASSWD sudo)${NC}"
    return 1
  }
  echo -e "${GREEN}✓ Plugin restarted${NC}"
}

# --- Initial sync ---
echo -e "${CYAN}▸ Performing initial sync...${NC}"
if [[ "$MODE" != "frontend" ]]; then
  sync_backend
fi
if [[ "$MODE" != "backend" ]]; then
  sync_frontend
fi
restart_plugin
echo ""

# Exit here when running in deploy-only mode (no watcher needed)
if [[ "$DEPLOY_ONLY" == "true" ]]; then
  echo -e "${GREEN}✓ Deploy complete${NC}"
  exit 0
fi

# --- Watch patterns ---
BACKEND_PATTERNS=("$REPO_DIR/main.py" "$REPO_DIR/backend" "$REPO_DIR/defaults" "$REPO_DIR/assets" "$REPO_DIR/plugin.json")
FRONTEND_PATTERNS=("$REPO_DIR/src")

WATCH_PATHS=()
if [[ "$MODE" != "frontend" ]]; then
  WATCH_PATHS+=("${BACKEND_PATTERNS[@]}")
fi
if [[ "$MODE" != "backend" ]]; then
  WATCH_PATHS+=("${FRONTEND_PATTERNS[@]}")
fi

echo -e "${CYAN}▸ Watching for changes (mode: ${MODE})...${NC}"
echo -e "${CYAN}  Press Ctrl+C to stop${NC}"
echo ""

# Debounce: batch events over 1 second
fswatch -o -l 1 \
  --exclude '\.pyc$' \
  --exclude '__pycache__' \
  --exclude '\.git' \
  --exclude 'node_modules' \
  --exclude '\.venv' \
  "${WATCH_PATHS[@]}" | while read -r _count; do

  TIMESTAMP=$(date +"%H:%M:%S")
  echo -e "${CYAN}[${TIMESTAMP}] Change detected${NC}"

  NEED_RESTART=false

  if [[ "$MODE" != "frontend" ]]; then
    sync_backend && NEED_RESTART=true
  fi

  if [[ "$MODE" != "backend" ]]; then
    # Check if any frontend files changed
    sync_frontend && NEED_RESTART=true
  fi

  if [[ "$NEED_RESTART" == "true" ]]; then
    restart_plugin
  fi

  echo ""
done
