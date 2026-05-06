# Documentation Maintenance

How to use the `@doc-keeper` agent for automated documentation maintenance.

## Overview

The `doc-keeper` agent scans for code changes since the last documentation update and brings all docs in sync with the codebase. It tracks its progress via `docs/.last-doc-update`.

## Manual Invocation

In VS Code Copilot Chat:

```
@doc-keeper Review and update all documentation to match the current codebase.
```

Or for a targeted update:

```
@doc-keeper Update docs/ARCHITECTURE.md to reflect changes in backend/bt_hid_service.py
```

## What It Checks

| Document | What It Validates |
|----------|-------------------|
| `README.md` | Features list, config table, installation steps, architecture diagram |
| `docs/ARCHITECTURE.md` | Component diagram, data flow, tech stack, state machine |
| `docs/BLUETOOTH.md` | Protocol details, HID descriptor layout, platform compat |
| `docs/STEAMOS.md` | System constraints, workarounds, file paths |
| `docs/DEVELOPMENT.md` | Setup instructions, project structure tree, build commands |
| `docs/ADR/` | Architecture Decision Records — creates new ones when decisions change |

## Change Triggers

The agent looks for these types of code changes:

- **New RPC methods**: New `async def` methods on `Plugin` class in `main.py`
- **Config changes**: New options in `defaults/defaults.json` or `Config` class
- **Component additions**: New files in `src/components/` or `src/hooks/`
- **BT protocol changes**: Modifications to `bt_hid_service.py`, `hid_descriptor.py`, `gamepad_sdp.xml`
- **Architecture changes**: New backend modules, changed data flow, dependency changes
- **Build/deploy changes**: `Makefile`, `package.json`, `rollup.config.js` modifications

## State File

The agent tracks its progress via `docs/.last-doc-update`:

```
<commit-hash>
```

This file contains the commit hash of the last code state that documentation was verified against. If the file doesn't exist, the agent treats all code as undocumented.

## ADR Creation

When the agent detects a significant architecture change, it creates a new ADR:

- File: `docs/ADR/NNN-title.md` (sequentially numbered after last existing ADR)
- Triggers: new services, D-Bus interface changes, dependency swaps, new communication patterns
- Current ADRs: `001-bt-hid-emulation.md`, `002-steamos-filesystem.md`

## Workflow Steps

1. **Read state**: Load `docs/.last-doc-update` for last checked commit
2. **Diff analysis**: `git log --oneline <last>..HEAD -- main.py backend/ src/ assets/ defaults/ plugin.json package.json`
3. **Code scan**: Read changed files, extract APIs, config, components
4. **Doc comparison**: Compare code reality with documented content
5. **Update docs**: Modify docs to match code
6. **Save state**: Write current HEAD hash to `docs/.last-doc-update`
7. **Report**: Summarize what was updated

## Automated Schedule (Optional)

To run doc maintenance automatically, add to `.github/workflows/doc-maintenance.yml`:

```yaml
name: Documentation Maintenance
on:
  schedule:
    - cron: '0 9 */3 * *'  # Every 3 days at 9 AM
  workflow_dispatch:

jobs:
  update-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Run doc-keeper
        run: |
          # Use GitHub Copilot CLI or custom script
          echo "Run @doc-keeper agent here"
      - name: Create PR
        uses: peter-evans/create-pull-request@v6
        with:
          title: "docs: automated documentation sync"
          body: "Documentation updated by doc-keeper agent"
          branch: docs/auto-update
```

## Review Process

1. Agent makes changes to documentation files
2. Changes should be committed on a branch (not directly to main)
3. Create a PR for human review
4. Reviewer verifies that doc changes match actual code behavior
5. Merge after approval

## Tips

- Run the agent after completing a feature branch, before PR review
- If docs are significantly out of date, run once and review carefully
- The agent preserves existing doc formatting and style
- For large refactors, invoke with specific file targets for focused updates
- Check agent memory for summaries of previous runs
