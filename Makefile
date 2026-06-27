.PHONY: setup test refresh dev verify

setup:
	python3 -m venv .venv
	.venv/bin/pip install -e 'pipeline[dev]'
	cd web && npm install

test:
	.venv/bin/pytest pipeline/tests
	cd web && npm test

refresh:
	./scripts/refresh-snapshot.sh

dev:
	cd web && npm run dev

verify: test
	cd web && npm run build
	cd web && npm run e2e
