# Local Pre-Deploy Verification

Full local verification pipeline that replaces CI. Run before every deploy to catch issues early.

## Quick Run

```bash
cd /Users/stralstsou/Documents/github/deck-controller
make verify
```

## What It Checks

### 1. Frontend Build (TypeScript + Rollup)

```bash
pnpm run build
```

- TypeScript compilation (strict mode via tsconfig.json)
- Rollup bundling → `dist/index.js`
- Verifies output file exists and is non-empty

### 2. Python Lint & Type Check

```bash
# Formatting
black --check backend/ main.py

# Import ordering
isort --check-only --profile black backend/ main.py

# Lint
flake8 backend/ main.py --max-line-length 100

# Type check
mypy backend/ main.py --ignore-missing-imports
```

### 3. Plugin Structure Validation

Verifies all required files exist for a valid DeckyLoader plugin:
- `plugin.json` — plugin metadata
- `main.py` — backend entry point
- `dist/index.js` — built frontend bundle
- `backend/` — Python backend package
- `assets/gamepad_sdp.xml` — SDP service record
- `defaults/defaults.json` — default config

### 4. ZIP Package Integrity

```bash
make deploy
```

- Creates `deck-controller.zip` with correct structure
- Verifies ZIP contains all required files

## Install Lint Tools (one-time)

```bash
pip install flake8 mypy black isort
```

## Makefile Targets

| Target | Purpose |
|--------|---------|
| `make lint` | Run Python linters (black, isort, flake8, mypy) |
| `make verify` | Full pipeline: lint → build → structure check |
| `make deploy` | Build + package into ZIP |

## When to Run

- **Before every commit**: `make lint` (fast, Python only)
- **Before deploy/release**: `make verify` (full pipeline)
- **To create release ZIP**: `make deploy`

## Troubleshooting

### black/isort formatting failures
```bash
black backend/ main.py        # auto-fix formatting
isort --profile black backend/ main.py  # auto-fix imports
```

### mypy errors with missing stubs
Add `--ignore-missing-imports` flag (already included) or install stubs:
```bash
pip install types-evdev types-dbus-python
```

### Frontend build fails
```bash
pnpm install   # reinstall deps
pnpm run build # retry
```
