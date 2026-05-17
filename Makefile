.PHONY: build clean deploy init lint verify test test-py test-ts format hooks-install hooks-run watch watch-backend watch-frontend deck-logs deck-errors

PYTHON := .venv/bin/python
PIP := .venv/bin/pip

build:
	pnpm i
	pnpm run build

clean:
	rm -rf dist/ out/ node_modules/

lint:
	$(PYTHON) -m black --check backend/ main.py
	$(PYTHON) -m isort --check-only --profile black backend/ main.py
	$(PYTHON) -m flake8 backend/ main.py --max-line-length 100
	$(PYTHON) -m mypy backend/ main.py --ignore-missing-imports
	pnpm exec eslint src/
	pnpm exec prettier --check src/

test-py:
	$(PYTHON) -m pytest --tb=short -q

test-ts:
	pnpm exec vitest run

test: test-py test-ts

format:
	$(PYTHON) -m black backend/ main.py
	$(PYTHON) -m isort backend/ main.py
	pnpm exec prettier --write src/

hooks-install:
	$(PYTHON) -m pre_commit install

hooks-run:
	$(PYTHON) -m pre_commit run --all-files

verify: lint test build
	@echo "=== Checking plugin structure ==="
	@test -f plugin.json || (echo "FAIL: plugin.json missing" && exit 1)
	@test -f main.py || (echo "FAIL: main.py missing" && exit 1)
	@test -f dist/index.js || (echo "FAIL: dist/index.js missing — build failed?" && exit 1)
	@test -d backend || (echo "FAIL: backend/ missing" && exit 1)
	@test -f assets/gamepad_sdp.xml || (echo "FAIL: assets/gamepad_sdp.xml missing" && exit 1)
	@test -f defaults/defaults.json || (echo "FAIL: defaults/defaults.json missing" && exit 1)
	@echo "=== All checks passed ==="

deploy: build
	mkdir -p out
	cp -r dist defaults assets plugin.json package.json main.py backend LICENSE README.md out/
	cd out && zip -r ../deck-controller.zip .
	rm -rf out

init:
	pnpm install

watch:
	@chmod +x scripts/live-reload.sh
	@scripts/live-reload.sh

watch-backend:
	@chmod +x scripts/live-reload.sh
	@scripts/live-reload.sh --backend-only

watch-frontend:
	@chmod +x scripts/live-reload.sh
	@scripts/live-reload.sh --frontend-only

deck-logs:
	@set -a && [ -f .env.deck ] && . ./.env.deck; set +a; \
	HOST=$${DECK_USER:-deck}@$${DECK_HOST:-192.168.0.199}; \
	echo "=== DeckyLoader log (last 50 lines) ==="; \
	ssh $$HOST "tail -50 ~/homebrew/logs/decky.log 2>/dev/null || echo '(not found)'"; \
	echo ""; \
	echo "=== Frontend errors ==="; \
	ssh $$HOST "cat ~/homebrew/settings/deck-controller/frontend-errors.log 2>/dev/null || echo '(no frontend errors)'"; \
	echo ""; \
	echo "=== Plugin logs (last 30 lines each) ==="; \
	ssh $$HOST "for f in ~/homebrew/logs/deck-controller/*.log; do [ -f \"\$$f\" ] && echo \"--- \$$f ---\" && tail -30 \"\$$f\"; done 2>/dev/null || echo '(no plugin logs)'"

deck-errors:
	@set -a && [ -f .env.deck ] && . ./.env.deck; set +a; \
	HOST=$${DECK_USER:-deck}@$${DECK_HOST:-192.168.0.199}; \
	echo "=== Frontend errors ==="; \
	ssh $$HOST "cat ~/homebrew/settings/deck-controller/frontend-errors.log 2>/dev/null || echo '(no frontend errors)'"; \
	echo ""; \
	echo "=== Errors in decky.log (last 20 matches) ==="; \
	ssh $$HOST "grep -iE '(error|exception|traceback)' ~/homebrew/logs/decky.log 2>/dev/null | grep -i 'deck.controller\|deck-controller' | tail -20 || echo '(no matches)'"
