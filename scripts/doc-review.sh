#!/usr/bin/env bash
# Documentation review via GitHub Copilot CLI — runs every 2 days via launchd
# Invokes Copilot autonomously to analyze code changes and update documentation

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REVIEWS_DIR="$REPO_DIR/docs/.reviews"
TIMESTAMP="$(date +%Y-%m-%d_%H%M)"
LOG_FILE="$REVIEWS_DIR/doc-review-${TIMESTAMP}.md"
LAST_DOC_FILE="$REPO_DIR/docs/.last-doc-update"

mkdir -p "$REVIEWS_DIR" "$REVIEWS_DIR/logs"
cd "$REPO_DIR"

# --- Determine baseline commit ---
if [ -f "$LAST_DOC_FILE" ]; then
  LAST_COMMIT="$(cat "$LAST_DOC_FILE" | tr -d '[:space:]')"
  if ! git cat-file -t "$LAST_COMMIT" &>/dev/null; then
    LAST_COMMIT="$(git rev-list --max-parents=0 HEAD)"
  fi
else
  LAST_COMMIT="$(git rev-list --max-parents=0 HEAD)"
fi

HEAD_COMMIT="$(git rev-parse HEAD)"

# Skip if no changes
if [ "$LAST_COMMIT" = "$HEAD_COMMIT" ]; then
  echo "[$(date)] No changes since last doc review. Skipping."
  exit 0
fi

# --- Collect context ---
CHANGED_CODE="$(git diff --name-only "$LAST_COMMIT".."$HEAD_COMMIT" -- \
  main.py backend/ src/ assets/ defaults/ plugin.json package.json Makefile 2>/dev/null || echo "none")"

COMMIT_LOG="$(git log --oneline "$LAST_COMMIT".."$HEAD_COMMIT" 2>/dev/null | head -30)"
COMMIT_COUNT="$(echo "$COMMIT_LOG" | grep -c . || echo 0)"

echo "[$(date)] Starting doc review: $COMMIT_COUNT commits since ${LAST_COMMIT:0:7}"

# --- Build prompt ---
read -r -d '' PROMPT << 'PROMPT_END' || true
You are the doc-keeper agent for the deck-controller project.

## Context

PROMPT_END

PROMPT="${PROMPT}
Period: ${LAST_COMMIT:0:7}..${HEAD_COMMIT:0:7} ($COMMIT_COUNT commits)

Changed code files:
$CHANGED_CODE

Recent commits:
$COMMIT_LOG

## Your Task

1. Read the changed code files listed above to understand what changed
2. Cross-reference with documentation in docs/ and README.md
3. For each code change, verify corresponding doc is still accurate:
   - New/changed RPC methods → README.md API section, docs/ARCHITECTURE.md
   - Config changes → README.md config table
   - BT protocol changes → docs/BLUETOOTH.md
   - New components → docs/ARCHITECTURE.md component diagram
   - Build/deploy changes → docs/DEVELOPMENT.md
4. UPDATE any stale or incorrect documentation directly
5. If a significant architecture decision was made, create a new ADR in docs/ADR/
6. Write the current HEAD ($HEAD_COMMIT) to docs/.last-doc-update
7. Commit all changes with message: docs: automated documentation sync

Rules:
- Do NOT add documentation for features that don't exist in code
- Do NOT modify code files — only documentation
- Keep existing formatting style
- Verify claims against actual source before updating"

# --- Run Copilot CLI in autopilot ---
echo "[$(date)] Invoking Copilot CLI..."

gh copilot \
  -p "$PROMPT" \
  --autopilot \
  --allow-all-tools \
  --allow-all-paths \
  --no-ask-user \
  --log-dir "$REVIEWS_DIR/logs" \
  --share "$LOG_FILE" \
  2>&1 | tee "$REVIEWS_DIR/doc-review-${TIMESTAMP}-output.log"

EXIT_CODE=$?

echo "[$(date)] Copilot CLI exited with code $EXIT_CODE"

if [ $EXIT_CODE -eq 0 ]; then
  osascript -e "display notification \"Doc review completed ($COMMIT_COUNT commits analyzed). Check docs/.reviews/\" with title \"Deck Controller\" subtitle \"📚 Doc Review ✅\"" 2>/dev/null || true
else
  osascript -e "display notification \"Doc review failed (exit $EXIT_CODE). Check logs.\" with title \"Deck Controller\" subtitle \"📚 Doc Review ❌\"" 2>/dev/null || true
fi

# --- Cleanup old reports (keep last 20) ---
ls -t "$REVIEWS_DIR"/doc-review-*.md 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null || true
ls -t "$REVIEWS_DIR"/doc-review-*-output.log 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null || true
