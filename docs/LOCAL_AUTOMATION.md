# Local Automation (Doc & Code Review)

This repository provides local automation scripts that use the GitHub Copilot CLI to perform periodic documentation and code reviews, and to sync docs/ to the GitHub Wiki.

What is included

- scripts/doc-review.sh — analyzes changed code and updates documentation where appropriate (writes reports to docs/.reviews/)
- scripts/code-review.sh — runs a Copilot-based code reviewer and saves reports to docs/.reviews/
- scripts/wiki-sync.sh — syncs docs/ into the project GitHub Wiki repository
- scripts/setup-automation.sh — installs macOS launchd jobs that schedule the above scripts; plists are in scripts/launchd/

Install (macOS / launchd)

```bash
./scripts/setup-automation.sh install
```

Manual runs

```bash
./scripts/doc-review.sh
./scripts/code-review.sh
./scripts/wiki-sync.sh
```

Logs and reports

- Reports and human-readable outputs are stored in `docs/.reviews/`.
- Launchd stdout/stderr log paths are configured in `scripts/launchd/` and also written to `docs/.reviews/`.

Notes

- Local automation is the recommended approach for development machines; CI-based automation (e.g., GitHub Actions) may still be used but is considered optional/legacy in this repository's current configuration.
- The automation relies on `gh` (GitHub CLI) and its Copilot CLI plugin; ensure `gh auth login` has been completed before installing.
