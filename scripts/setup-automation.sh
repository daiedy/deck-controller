#!/usr/bin/env bash
# Install/uninstall/manage local review automation via launchd + Copilot CLI

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_DIR="$SCRIPT_DIR/launchd"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

PLISTS=(
  "com.deck-controller.doc-review.plist"
  "com.deck-controller.code-review.plist"
)

install() {
  # Verify Copilot CLI is available
  if ! command -v gh &>/dev/null; then
    echo "❌ Error: gh CLI not found. Install: brew install gh"
    exit 1
  fi

  if ! gh auth status &>/dev/null; then
    echo "❌ Error: gh not authenticated. Run: gh auth login"
    exit 1
  fi

  echo "Checking Copilot CLI..."
  gh copilot -- --version 2>/dev/null || {
    echo "Installing Copilot CLI..."
    gh copilot -- --version
  }

  mkdir -p "$LAUNCH_AGENTS_DIR"
  mkdir -p "$REPO_DIR/docs/.reviews/logs"

  # Make scripts executable
  chmod +x "$SCRIPT_DIR/doc-review.sh"
  chmod +x "$SCRIPT_DIR/code-review.sh"

  for plist in "${PLISTS[@]}"; do
    echo "Installing $plist..."
    cp "$PLIST_DIR/$plist" "$LAUNCH_AGENTS_DIR/$plist"
    launchctl unload "$LAUNCH_AGENTS_DIR/$plist" 2>/dev/null || true
    launchctl load "$LAUNCH_AGENTS_DIR/$plist"
    echo "  ✅ Loaded"
  done

  echo ""
  echo "═══════════════════════════════════════════"
  echo "  ✅ Local review automation installed!"
  echo "═══════════════════════════════════════════"
  echo ""
  echo "  📚 Doc review:  every 2 days (Copilot CLI → updates docs)"
  echo "  🔍 Code review: every 3 days (Copilot CLI → reports issues)"
  echo ""
  echo "  Reports:  docs/.reviews/*.md"
  echo "  Logs:     docs/.reviews/logs/"
  echo "  Sessions: docs/.reviews/*-output.log"
  echo ""
  echo "  Run manually:"
  echo "    ./scripts/doc-review.sh"
  echo "    ./scripts/code-review.sh"
  echo ""
  echo "  Manage:"
  echo "    ./scripts/setup-automation.sh status"
  echo "    ./scripts/setup-automation.sh uninstall"
  echo ""
}

uninstall() {
  for plist in "${PLISTS[@]}"; do
    if [ -f "$LAUNCH_AGENTS_DIR/$plist" ]; then
      echo "Unloading $plist..."
      launchctl unload "$LAUNCH_AGENTS_DIR/$plist" 2>/dev/null || true
      rm "$LAUNCH_AGENTS_DIR/$plist"
      echo "  ✅ Removed"
    else
      echo "  ⏭ $plist not installed"
    fi
  done
  echo ""
  echo "All review jobs removed. Reports in docs/.reviews/ are preserved."
}

status() {
  echo ""
  echo "Deck Controller — Local Review Automation"
  echo "══════════════════════════════════════════"
  echo ""

  for plist in "${PLISTS[@]}"; do
    LABEL="${plist%.plist}"
    if launchctl list "$LABEL" &>/dev/null 2>&1; then
      PID="$(launchctl list "$LABEL" 2>/dev/null | awk 'NR==2{print $1}')"
      echo "  ✅ $LABEL (PID: ${PID:-idle})"
    else
      echo "  ❌ $LABEL — not loaded"
    fi
  done

  echo ""
  echo "Recent reports:"
  ls -lt "$REPO_DIR/docs/.reviews"/*.md 2>/dev/null | head -5 | awk '{print "  " $6, $7, $8, $9}' || echo "  No reports yet"

  echo ""
  echo "Copilot CLI:"
  gh copilot -- --version 2>/dev/null || echo "  ❌ Not installed"

  echo ""
}

run_now() {
  case "${2:-all}" in
    doc|docs)
      echo "Running doc review now..."
      "$SCRIPT_DIR/doc-review.sh"
      ;;
    code)
      echo "Running code review now..."
      "$SCRIPT_DIR/code-review.sh"
      ;;
    wiki)
      echo "Running wiki sync now..."
      "$SCRIPT_DIR/wiki-sync.sh"
      ;;
    all|*)
      echo "Running all reviews..."
      "$SCRIPT_DIR/doc-review.sh"
      "$SCRIPT_DIR/code-review.sh"
      ;;
  esac
}

case "${1:-help}" in
  install)    install ;;
  uninstall)  uninstall ;;
  status)     status ;;
  run)        run_now "$@" ;;
  *)
    echo "Usage: $0 {install|uninstall|status|run [doc|code|wiki|all]}"
    echo ""
    echo "  install   — Install launchd jobs + verify Copilot CLI"
    echo "  uninstall — Remove launchd jobs"
    echo "  status    — Show job status + recent reports"
    echo "  run       — Run reviews immediately (doc/code/wiki/all)"
    ;;
esac
