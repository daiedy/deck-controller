.PHONY: build clean deploy init lint verify

build:
	pnpm i
	pnpm run build

clean:
	rm -rf dist/ out/ node_modules/

lint:
	black --check backend/ main.py
	isort --check-only --profile black backend/ main.py
	flake8 backend/ main.py --max-line-length 100
	mypy backend/ main.py --ignore-missing-imports

verify: lint build
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
