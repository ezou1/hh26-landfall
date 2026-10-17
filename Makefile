# LANDFALL - hurricane prediction and response-logistics planner.
# Targets: install, data, train, precompute, serve, demo, check, test, lint, clean.

SHELL := /bin/bash
.ONESHELL:
.DEFAULT_GOAL := help

-include .env
export

CHALK_MODE ?= local
LANDFALL_SEED ?= 42
API_PORT ?= 8000
WEB_PORT ?= 5173
UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
PY := PYTHONPATH=$(CURDIR) $(CURDIR)/.venv/bin/python
# Load nvm if node is not on the PATH (a Windows npm on the WSL PATH does not count).
NODE_SETUP := if ! command -v node >/dev/null 2>&1 && [ -s "$$HOME/.nvm/nvm.sh" ]; then . "$$HOME/.nvm/nvm.sh" >/dev/null; fi;

.PHONY: chalk-apply help install install-py install-web data train precompute serve demo check test lint ste clean clean-all open

help:
	@echo "make demo        install, download data, train, precompute, and start the UI"
	@echo "make install     install the Python and web dependencies"
	@echo "make data        download and cache every data source (fallbacks on failure)"
	@echo "make train       build the Chalk training frame and train the predictor"
	@echo "make precompute  run Stage 1-3 and write out/ (FORCE=1 to recompute)"
	@echo "make serve       start the API (:$(API_PORT)) and the web UI (:$(WEB_PORT))"
	@echo "make check       ruff, pytest, tsc --noEmit, eslint, STE lint"
	@echo "make chalk-apply bundle chalk/data and deploy chalk/ to Chalk (BRANCH=name for a branch)"

install: install-py install-web

install-py:
	@if [ ! -x "$(UV)" ]; then python3 -m pip install --user --quiet uv; fi
	$(UV) sync --extra dev --quiet

install-web:
	@$(NODE_SETUP) cd web && (npm ci --no-audit --no-fund --loglevel=error || npm install --no-audit --no-fund --loglevel=error)

data: install-py
	$(PY) scripts/download_data.py

train: data
	$(PY) -c "from landfall.predict.train import train; train(refresh=False)"

precompute: train
	$(PY) scripts/precompute.py $(if $(FORCE),--force,)

serve:
	@$(NODE_SETUP) set -m
	trap 'kill 0' EXIT INT TERM
	$(PY) -m uvicorn api.main:app --host 0.0.0.0 --port $(API_PORT) --log-level warning &
	(cd web && VITE_CESIUM_ION_TOKEN="$(CESIUM_ION_TOKEN)" npx vite --host 0.0.0.0 --port $(WEB_PORT) --strictPort) &
	for i in $$(seq 1 60); do curl -fs http://localhost:$(WEB_PORT) >/dev/null 2>&1 && break; sleep 1; done
	echo "LANDFALL UI: http://localhost:$(WEB_PORT)  (API: http://localhost:$(API_PORT)/api/health)"
	$(MAKE) --no-print-directory open
	wait

open:
	@(command -v wslview >/dev/null && wslview http://localhost:$(WEB_PORT)) || \
	 (command -v xdg-open >/dev/null && xdg-open http://localhost:$(WEB_PORT) >/dev/null 2>&1) || \
	 (command -v cmd.exe >/dev/null && cmd.exe /c start http://localhost:$(WEB_PORT) >/dev/null 2>&1) || \
	 (command -v open >/dev/null && open http://localhost:$(WEB_PORT)) || true

demo: install precompute serve

test:
	$(PY) -m pytest -q

lint:
	$(CURDIR)/.venv/bin/ruff check landfall chalk api scripts tests
	@$(NODE_SETUP) cd web && npm run --silent typecheck && npm run --silent lint

ste:
	$(PY) scripts/ste_lint.py --quiet-warnings

check: lint test ste

chalk-apply:
	$(PY) scripts/chalk_bundle.py
	cd chalk && . ../.venv/bin/activate && chalk apply $(if $(BRANCH),--branch $(BRANCH),)

clean:
	rm -rf out

clean-all: clean
	rm -rf data/raw data/cache .venv web/node_modules
