# Deploy to Steam Deck

How to deploy Deck Controller to a Steam Deck over SSH.

## Configuration

All settings live in `.env.deck` (gitignored, never committed):

```bash
# .env.deck
DECK_HOST=192.168.0.199
DECK_USER=deck
DECK_PLUGIN_DIR=/home/deck/homebrew/plugins/deck-controller
DECK_PASS=<sudo password>   # needed for sudo cp / systemctl restart
```

> **Note:** `DECK_PLUGIN_DIR` must be an **absolute path** — `~/` expands on the Mac, not on the Deck.

## Deploy Backend Only (most common)

Use this after changing any Python file (`main.py`, `backend/`, `defaults/`, `assets/`):

```bash
cd /Users/stralstsou/Documents/github/deck-controller

# One-shot: sync + restart plugin, then exit (no watcher)
bash scripts/live-reload.sh --backend-only < /dev/null &
DEPLOY_PID=$!; sleep 12; kill $DEPLOY_PID 2>/dev/null; wait $DEPLOY_PID 2>/dev/null
```

Or run it via the terminal directly and press Ctrl+C after "✓ Plugin restarted" appears.

## Deploy Frontend Only

Use this after changing anything in `src/`:

```bash
bash scripts/live-reload.sh --frontend-only < /dev/null &
DEPLOY_PID=$!; sleep 30; kill $DEPLOY_PID 2>/dev/null; wait $DEPLOY_PID 2>/dev/null
```

Frontend build takes ~15s.

## Deploy Both (full deploy)

```bash
bash scripts/live-reload.sh < /dev/null &
DEPLOY_PID=$!; sleep 35; kill $DEPLOY_PID 2>/dev/null; wait $DEPLOY_PID 2>/dev/null
```

## What the Script Does

1. rsync files to `/tmp/deck-controller-deploy/` on the Deck
2. `sudo bash -c 'cp -rf /tmp/deck-controller-deploy/* /home/deck/homebrew/plugins/deck-controller/'`
   - Uses `sudo -n` (non-interactive) — allowed via NOPASSWD rule for `/usr/bin/bash -c *`
3. `sudo systemctl restart plugin_loader`
   - Also NOPASSWD for this command

## Verify After Deploy

```bash
make deck-logs
```

Check for errors in the DeckyLoader log. Plugin should load within 5s of restart.

## SSH Connectivity

```bash
ssh deck@192.168.0.199 echo "ok"
```

If this fails, wake the Deck and ensure SSH is running:
```bash
# On the Deck (Desktop mode → terminal):
sudo systemctl start sshd
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `sudo: a password is required` | `DECK_PASS` not set in `.env.deck` | Add `DECK_PASS=<password>` to `.env.deck` |
| `cp: target '...': No such file or directory` | `DECK_PLUGIN_DIR` uses `~/` | Change to absolute path `/home/deck/...` |
| `Cannot connect to deck@...` | Deck asleep or SSH stopped | Wake Deck, run `sudo systemctl start sshd` |
| `sudo -n ... permission denied` | NOPASSWD sudoers rule missing | Run `sudo -l` on Deck to check; use `sshpass` approach |

## NOPASSWD Sudoers (pre-configured on this Deck)

The Deck already has these NOPASSWD rules (no changes needed):
```
(ALL) NOPASSWD: /usr/bin/systemctl restart plugin_loader
(ALL) NOPASSWD: /usr/bin/bash -c *
```
