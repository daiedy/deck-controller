#!/usr/bin/env bash
# Wiki sync via GitHub Copilot CLI — keeps wiki pages in sync with docs/
# Runs as part of doc-review cycle or independently

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REVIEWS_DIR="$REPO_DIR/docs/.reviews"
TIMESTAMP="$(date +%Y-%m-%d_%H%M)"
LOG_FILE="$REVIEWS_DIR/wiki-sync-${TIMESTAMP}.md"
WIKI_DIR="$REPO_DIR/.wiki-checkout"
WIKI_REPO="https://github.com/daiedy/deck-controller.wiki.git"

mkdir -p "$REVIEWS_DIR" "$REVIEWS_DIR/logs"
cd "$REPO_DIR"

# --- Clone or update wiki repo ---
if [ -d "$WIKI_DIR/.git" ]; then
  echo "[$(date)] Updating wiki checkout..."
  git -C "$WIKI_DIR" pull --rebase --quiet 2>/dev/null || {
    echo "[$(date)] Wiki pull failed, re-cloning..."
    rm -rf "$WIKI_DIR"
    git clone "$WIKI_REPO" "$WIKI_DIR" --quiet
  }
else
  echo "[$(date)] Cloning wiki..."
  git clone "$WIKI_REPO" "$WIKI_DIR" --quiet 2>/dev/null || {
    echo "[$(date)] ERROR: Cannot clone wiki. Is it initialized on GitHub?"
    echo "  Go to https://github.com/daiedy/deck-controller/wiki and create at least one page."
    exit 1
  }
fi

# --- Collect current state ---
WIKI_PAGES="$(ls "$WIKI_DIR"/*.md 2>/dev/null | xargs -I{} basename {} | sort)"
DOC_FILES="$(ls "$REPO_DIR"/docs/*.md 2>/dev/null | xargs -I{} basename {} | sort)"

# Get recent changes in docs/
LAST_WIKI_SYNC_FILE="$REPO_DIR/docs/.last-wiki-sync"
if [ -f "$LAST_WIKI_SYNC_FILE" ]; then
  LAST_COMMIT="$(cat "$LAST_WIKI_SYNC_FILE" | tr -d '[:space:]')"
  if ! git cat-file -t "$LAST_COMMIT" &>/dev/null; then
    LAST_COMMIT="$(git rev-list --max-parents=0 HEAD)"
  fi
else
  LAST_COMMIT="$(git log --oneline -20 --format=%H | tail -1)"
fi

HEAD_COMMIT="$(git rev-parse HEAD)"
CHANGED_DOCS="$(git diff --name-only "$LAST_COMMIT".."$HEAD_COMMIT" -- docs/ README.md 2>/dev/null || echo "")"

if [ -z "$CHANGED_DOCS" ]; then
  echo "[$(date)] No documentation changes since last wiki sync. Skipping."
  exit 0
fi

echo "[$(date)] Docs changed since last sync:"
echo "$CHANGED_DOCS"

# --- Build prompt for Copilot ---
PROMPT="You are responsible for keeping the GitHub Wiki for daiedy/deck-controller in sync with the main repository documentation.

## Source of Truth
The canonical documentation lives in the repo:
- README.md — project overview, features, quick start, config
- docs/ARCHITECTURE.md — architecture, components, data flow
- docs/BLUETOOTH.md — Bluetooth HID protocol details
- docs/STEAMOS.md — SteamOS constraints and workarounds
- docs/DEVELOPMENT.md — developer setup, build, contribute
- docs/ADR/ — architecture decision records

## Wiki Location
The wiki is checked out at: $WIKI_DIR
Each .md file in that directory is a wiki page. The filename (without .md) is the page title in the wiki.

## Current Wiki Pages
$WIKI_PAGES

## Changed Source Docs (since last sync)
$CHANGED_DOCS

## Your Task

1. Read the changed source docs listed above
2. For each changed doc, find the corresponding wiki page(s) and update them
3. Wiki pages should be:
   - Written for HUMANS, not developers — friendly, clear, approachable
   - Well-structured with headers, tables, and examples
   - Contain the same factual content as the source docs but in wiki-appropriate format
   - Cross-linked to other wiki pages where relevant (use [[Page Name]] syntax)
   - NOT a copy-paste of the source docs — adapt the content for wiki readers

4. Mapping (source → wiki pages):
   - README.md → Home.md (main wiki page)
   - docs/ARCHITECTURE.md → Architecture.md
   - docs/BLUETOOTH.md → Bluetooth-Protocol.md
   - docs/STEAMOS.md → SteamOS-Notes.md
   - docs/DEVELOPMENT.md → Development-Guide.md, Building.md
   - docs/ADR/*.md → Architecture-Decisions.md (summary page)

5. After updating, commit and push the wiki:
   cd $WIKI_DIR
   git add -A
   git commit -m \"docs: sync wiki with repo docs ($TIMESTAMP)\"
   git push

6. Write the current HEAD ($HEAD_COMMIT) to docs/.last-wiki-sync in the MAIN repo

Rules:
- Keep wiki pages friendly and readable — use simple language
- Add a sidebar (_Sidebar.md) if it doesn't exist, listing all pages
- Don't remove wiki-only content (like guides or FAQ) that doesn't exist in docs
- If a wiki page has NO corresponding source doc, leave it alone
- Mermaid diagrams: use SIMPLE syntax, avoid parentheses in edge labels, avoid <br/> — use \\n instead"

# --- Run Copilot CLI ---
echo "[$(date)] Invoking Copilot CLI for wiki sync..."

gh copilot \
  -p "$PROMPT" \
  --autopilot \
  --allow-all-tools \
  --allow-all-paths \
  --no-ask-user \
  --log-dir "$REVIEWS_DIR/logs" \
  --share "$LOG_FILE" \
  2>&1 | tee "$REVIEWS_DIR/wiki-sync-${TIMESTAMP}-output.log"

EXIT_CODE=$?

echo "[$(date)] Copilot CLI exited with code $EXIT_CODE"

if [ $EXIT_CODE -eq 0 ]; then
  osascript -e "display notification \"Wiki synced with latest docs.\" with title \"Deck Controller\" subtitle \"📚 Wiki Sync ✅\"" 2>/dev/null || true
else
  osascript -e "display notification \"Wiki sync failed (exit $EXIT_CODE).\" with title \"Deck Controller\" subtitle \"📚 Wiki Sync ❌\"" 2>/dev/null || true
fi

# --- Cleanup old logs (keep last 10) ---
ls -t "$REVIEWS_DIR"/wiki-sync-*.md 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
ls -t "$REVIEWS_DIR"/wiki-sync-*-output.log 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
