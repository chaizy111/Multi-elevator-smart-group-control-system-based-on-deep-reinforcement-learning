PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
export PYTHONPATH := $(CURDIR)/src
export PYTHONDONTWRITEBYTECODE := 1
export MPLCONFIGDIR := $(CURDIR)/.cache/matplotlib
export XDG_CACHE_HOME := $(CURDIR)/.cache
export TMPDIR := $(CURDIR)/.cache/tmp
export npm_config_cache := $(CURDIR)/.cache/npm
export PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.cache/playwright
export ELEVATOR_PYTHON := $(shell "$(PYTHON)" -c 'import sys; print(sys.executable)')

.PHONY: bootstrap test lint dev demo frontend-build acceptance-smoke benchmark
bootstrap:
	bash scripts/bootstrap.sh
test:
	$(PYTHON) -m pytest
	npm --prefix frontend run test
lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m pyright --pythonpath $(PYTHON)
	npm --prefix frontend run typecheck
frontend-build:
	npm --prefix frontend run build
dev: frontend-build
	$(PYTHON) -m elevator_control.cli serve
demo:
	ELEVATOR_PYTHON=$(PYTHON) bash scripts/run_demo.sh
acceptance-smoke: test frontend-build
	$(PYTHON) scripts/run_acceptance.py
	npm --prefix frontend run test:e2e
benchmark:
	$(PYTHON) -m elevator_control.cli benchmark --config configs/simulation/performance.yaml --output reports/benchmark.json
