.PHONY: install lint format test demo-quick sync-skills dist check-dist

PYTHON ?= python3
export PYTHONPATH := .$(if $(PYTHONPATH),:$(PYTHONPATH),)
export TOKENOPS_CONFIG ?= src/tokenops/config/default.yaml

install:
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	$(PYTHON) -m pip install -e ".[examples]" --group dev

lint:
	$(PYTHON) -m ruff check src tests examples
	$(PYTHON) -m ruff format --check src tests examples
	$(PYTHON) scripts/sync-skills.py --check
	$(PYTHON) -m mypy --python-version $$( $(PYTHON) -c 'import sys; print("%d.%d" % sys.version_info[:2])' )

format:
	$(PYTHON) -m ruff check --fix src tests examples
	$(PYTHON) -m ruff format src tests examples

test:
	$(PYTHON) -m pytest -q

# Smallest end-to-end run: no API keys, no server, no Docker.
# Ships inside the package, so `pip install agent-tokenops` is enough to run it.
demo-quick:
	$(PYTHON) -m tokenops.demo

# Regenerate the editor-specific copies of .claude/skills/integrate-tokenops.
sync-skills:
	$(PYTHON) scripts/sync-skills.py

# Build sdist + wheel under dist/ (see RELEASING.md).
dist:
	rm -rf dist build *.egg-info src/*.egg-info
	$(PYTHON) -m pip install -q "build>=1.2"
	$(PYTHON) -m build

check-dist: dist
	$(PYTHON) -m pip install -q "twine>=6"
	$(PYTHON) -m twine check dist/*
