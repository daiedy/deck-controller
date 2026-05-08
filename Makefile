.PHONY: build clean deploy init lint verify test test-py test-ts format hooks-install hooks-run

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
	cp -r dist defaults assets plugin.json main.py backend LICENSE README.md out/
	cd out && zip -r ../deck-controller.zip .
	rm -rf out

init:
	pnpm install
