.PHONY: build clean deploy init

build:
	pnpm i
	pnpm run build

clean:
	rm -rf dist/ out/ node_modules/

deploy: build
	mkdir -p out
	cp -r dist defaults assets plugin.json main.py backend LICENSE README.md out/
	cd out && zip -r ../deck-controller.zip .
	rm -rf out

init:
	pnpm install
