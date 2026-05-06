# Build Plugin

How to build the Deck Controller DeckyLoader plugin for development and release.

## Prerequisites

- **Node.js** 18+ (`node --version`)
- **pnpm** (`npm install -g pnpm` or `corepack enable`)
- **Python 3.10+** (for backend — runs directly, no build step)

## Quick Build

```bash
cd /Users/stralstsou/Documents/github/deck-controller

# Install dependencies + build frontend
make build
```

This runs `pnpm install` then `pnpm run build` (Rollup bundles `src/` → `dist/index.js`).

## Step-by-Step Build

### 1. Install Dependencies

```bash
pnpm install
```

This installs `@decky/api`, `@decky/ui`, `react`, `react-dom`, and dev tools (Rollup, TypeScript).

### 2. Build Frontend

```bash
pnpm run build
```

Rollup compiles TypeScript, bundles React components, and outputs `dist/index.js`.

### 3. Verify Build Output

```bash
ls -la dist/index.js
```

The file should exist and be non-empty. This is the only frontend artifact needed.

## Creating a Release ZIP

```bash
make deploy
```

This:
1. Runs `make build`
2. Creates an `out/` staging directory
3. Copies `dist/`, `defaults/`, `assets/`, `plugin.json`, `main.py`, `backend/` into it
4. Zips to `deck-controller.zip`
5. Cleans up `out/`

The ZIP is ready for sideloading or Decky Plugin Store submission.

## Frontend-Only Rebuild

When you've only changed files in `src/`:

```bash
pnpm run build
```

No need to reinstall dependencies. Then deploy just `dist/index.js` to the Deck.

## Full Clean Rebuild

When things are broken or you want a fresh start:

```bash
make clean && make build
```

This removes `dist/`, `out/`, and `node_modules/`, then reinstalls and rebuilds everything.

## Troubleshooting

### `pnpm: command not found`

```bash
npm install -g pnpm
# or
corepack enable && corepack prepare pnpm@latest --activate
```

### `Could not resolve @decky/api` or `@decky/ui`

```bash
rm -rf node_modules pnpm-lock.yaml
pnpm install
```

### Rollup errors about missing modules

Check `rollup.config.js` — ensure externals match what DeckyLoader provides at runtime (`react`, `react-dom`).

### TypeScript errors

```bash
npx tsc --noEmit
```

Fix type errors before building. The project uses `strict` TypeScript (`tsconfig.json`).

### Build output is empty or missing

Verify `src/index.tsx` has a default export from `definePlugin()`. Rollup needs this entry point.

### `make deploy` fails

Check that `make build` succeeds first. The deploy target depends on a successful build.

## Build Artifacts

| File/Directory | Purpose |
|---|---|
| `dist/index.js` | Bundled frontend (only file needed for frontend) |
| `deck-controller.zip` | Release archive for distribution |
| `node_modules/` | Dev dependencies (not shipped) |

## Backend

The Python backend (`main.py`, `backend/`) requires no build step. Python files run directly via DeckyLoader's Python runtime. Just copy them to the Deck.
