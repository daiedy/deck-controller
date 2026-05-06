#!/usr/bin/env bash
# Code review via GitHub Copilot CLI — runs every 3 days via launchd
# Invokes Copilot autonomously to review code quality, architecture drift, and plans

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REVIEWS_DIR="$REPO_DIR/docs/.reviews"
TIMESTAMP="$(date +%Y-%m-%d_%H%M)"
LOG_FILE="$REVIEWS_DIR/code-review-${TIMESTAMP}.md"
LAST_REVIEW_FILE="$REPO_DIR/docs/.last-code-review"

mkdir -p "$REVIEWS_DIR" "$REVIEWS_DIR/logs"
cd "$REPO_DIR"

# --- Determine baseline ---
if [ -f "$LAST_REVIEW_FILE" ]; then
  LAST_COMMIT="$(cat "$LAST_REVIEW_FILE" | tr -d '[:space:]')"
  if ! git cat-file -t "$LAST_COMMIT" &>/dev/null; then
    LAST_COMMIT="$(git rev-list --max-parents=0 HEAD)"
  fi
else
  LAST_COMMIT="$(git rev-list --max-parents=0 HEAD)"
fi

HEAD_COMMIT="$(git rev-parse HEAD)"

if [ "$LAST_COMMIT" = "$HEAD_COMMIT" ]; then
  echo "[$(date)] No changes since last code review. Skipping."
  exit 0
fi

# --- Collect context ---
CHANGED_PY="$(git diff --name-only "$LAST_COMMIT".."$HEAD_COMMIT" -- '*.py' 2>/dev/null || echo "")"
CHANGED_TS="$(git diff --name-only "$LAST_COMMIT".."$HEAD_COMMIT" -- '*.ts' '*.tsx' 2>/dev/null || echo "")"
CHANGED_ALL="$(git diff --name-only "$LAST_COMMIT".."$HEAD_COMMIT" 2>/dev/null || echo "")"
COMMIT_LOG="$(git log --oneline "$LAST_COMMIT".."$HEAD_COMMIT" 2>/dev/null | head -30)"
COMMIT_COUNT="$(echo "$COMMIT_LOG" | grep -c . || echo 0)"

# Get diff stats
DIFF_STAT="$(git diff --stat "$LAST_COMMIT".."$HEAD_COMMIT" 2>/dev/null | tail -1)"

echo "[$(date)] Starting code review: $COMMIT_COUNT commits since ${LAST_COMMIT:0:7}"

# --- Build prompt ---
PROMPT="You are a senior code reviewer for the deck-controller project (DeckyLoader plugin — Python backend + React frontend, Bluetooth HID emulation for Steam Deck).

## Context

Period: ${LAST_COMMIT:0:7}..${HEAD_COMMIT:0:7} ($COMMIT_COUNT commits)
Stats: $DIFF_STAT

Changed Python files:
${CHANGED_PY:-none}

Changed TypeScript files:
${CHANGED_TS:-none}

Recent commits:
$COMMIT_LOG

## Your Task — Full Code Review

### 1. Code Quality Review
For each changed file, check:
- Python: type hints, asyncio patterns, proper error handling, no bare excepts, no debug print()
- TypeScript: no \`any\` types, no console.log in production, proper hooks usage
- Both: security issues (hardcoded secrets, injection, unsafe deserialization)

### 2. Architecture Drift
- Read docs/ARCHITECTURE.md and docs/ADR/ for the intended architecture
- Check if new code follows established patterns
- Flag any code that contradicts documented architecture decisions
- Check if .planning/ roadmap (if exists) still aligns with implementation

### 3. Plan Alignment
- If .planning/ directory exists, read the current ROADMAP.md
- Verify that recent commits advance the planned work
- Flag unplanned changes that may need a plan update or new ADR

### 4. Issue Report
Write a structured review report as a markdown file. For each issue:
- File path and line range
- Severity: 🔴 critical / 🟡 warning / 🔵 suggestion
- Description and recommended fix

### 5. Update Marker
Write the current HEAD ($HEAD_COMMIT) to docs/.last-code-review

### 6. Commit
Commit the updated marker with message: chore: code review checkpoint ${TIMESTAMP}

Rules:
- Do NOT fix the code — only report issues
- Be specific: include file paths, line numbers, and code snippets
- Focus on bugs, security, and architecture — not style
- Check that Bluetooth/L2CAP socket code follows BlueZ best practices
- Verify all cleanup happens in _unload() method"

# --- Run Copilot CLI ---
echo "[$(date)] Invoking Copilot CLI..."

gh copilot \
  -p "$PROMPT" \
  --autopilot \
  --allow-all-tools \
  --allow-all-paths \
  --no-ask-user \
  --log-dir "$REVIEWS_DIR/logs" \
  --share "$LOG_FILE" \
  2>&1 | tee "$REVIEWS_DIR/code-review-${TIMESTAMP}-output.log"

EXIT_CODE=$?

echo "[$(date)] Copilot CLI exited with code $EXIT_CODE"

if [ $EXIT_CODE -eq 0 ]; then
  osascript -e "display notification \"Code review completed ($COMMIT_COUNT commits). Check docs/.reviews/\" with title \"Deck Controller\" subtitle \"🔍 Code Review ✅\"" 2>/dev/null || true
else
  osascript -e "display notification \"Code review failed (exit $EXIT_CODE). Check logs.\" with title \"Deck Controller\" subtitle \"🔍 Code Review ❌\"" 2>/dev/null || true
fi

# --- Cleanup old reports (keep last 15) ---
ls -t "$REVIEWS_DIR"/code-review-*.md 2>/dev/null | tail -n +16 | xargs rm -f 2>/dev/null || true
ls -t "$REVIEWS_DIR"/code-review-*-output.log 2>/dev/null | tail -n +16 | xargs rm -f 2>/dev/null || true
