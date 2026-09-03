.PHONY: install control-plane ui run stop \
	demo demo-triad demo-brief bench-ui \
	research-server summarize-server \
	planner-server researcher-server writer-server \
	scout-server analyst-server editor-server \
	stop-demo stop-triad stop-brief \
	db-clear db-reseed db-reset \
	dist check-dist \
	lint format test \
	quickstart sync-skills

PYTHON ?= python3
export PYTHONPATH := .$(if $(PYTHONPATH),:$(PYTHONPATH),)
export TOKENOPS_CONFIG ?= src/tokenops/config/default.yaml

install:
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	$(PYTHON) -m pip install -e ".[dev,examples]"

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
quickstart:
	$(PYTHON) examples/quickstart.py

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

control-plane:
	$(PYTHON) -m tokenops.server

# Plane-side product UI (Admin + Dashboard).
ui:
	streamlit run src/tokenops/ui/app.py --server.port 8501

run: stop
	$(PYTHON) -c "import os,subprocess,sys,time,signal; \
from pathlib import Path; \
os.environ.setdefault('TOKENOPS_CONFIG','src/tokenops/config/default.yaml'); \
p=subprocess.Popen([sys.executable,'-m','tokenops.server']); \
time.sleep(1); \
rc=subprocess.call([sys.executable,'-m','streamlit','run','src/tokenops/ui/app.py','--server.port=8501']); \
p.send_signal(signal.SIGTERM); p.wait(timeout=5); raise SystemExit(rc)"

stop:
	@for port in 7700 8501; do \
		pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null); \
		if [ -n "$$pids" ]; then \
			echo "Stopping listener on port $$port ($$pids)"; \
			kill $$pids 2>/dev/null || true; \
			sleep 0.5; \
			pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null); \
			if [ -n "$$pids" ]; then kill -9 $$pids 2>/dev/null || true; fi; \
		fi; \
	done

# --- Examples / demos ---

research-server:
	$(PYTHON) -m examples.servers.research

summarize-server:
	$(PYTHON) -m examples.servers.summarize

planner-server:
	TOKENOPS_CONFIG=$${TOKENOPS_CONFIG:-examples/config/triad.yaml} $(PYTHON) -m examples.servers.planner

researcher-server:
	TOKENOPS_CONFIG=$${TOKENOPS_CONFIG:-examples/config/triad.yaml} $(PYTHON) -m examples.servers.researcher

writer-server:
	TOKENOPS_CONFIG=$${TOKENOPS_CONFIG:-examples/config/triad.yaml} $(PYTHON) -m examples.servers.writer

scout-server:
	TOKENOPS_CONFIG=$${TOKENOPS_CONFIG:-examples/config/brief.yaml} $(PYTHON) -m examples.servers.scout

analyst-server:
	TOKENOPS_CONFIG=$${TOKENOPS_CONFIG:-examples/config/brief.yaml} $(PYTHON) -m examples.servers.analyst

editor-server:
	TOKENOPS_CONFIG=$${TOKENOPS_CONFIG:-examples/config/brief.yaml} $(PYTHON) -m examples.servers.editor

bench-ui:
	streamlit run examples/ui/app.py --server.port 8501

demo: stop-demo
	TOKENOPS_CONFIG=$${TOKENOPS_CONFIG:-examples/config/default.yaml} $(PYTHON) examples/run.py

demo-triad: stop-triad
	TOKENOPS_CONFIG=$${TOKENOPS_CONFIG:-examples/config/triad.yaml} $(PYTHON) examples/run_triad.py

demo-brief: stop-brief
	TOKENOPS_CONFIG=$${TOKENOPS_CONFIG:-examples/config/brief.yaml} $(PYTHON) examples/run_brief.py

stop-demo:
	@for port in 7700 8001 8002 8501; do \
		pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null); \
		if [ -n "$$pids" ]; then \
			echo "Stopping listener on port $$port ($$pids)"; \
			kill $$pids 2>/dev/null || true; \
			sleep 0.5; \
			pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null); \
			if [ -n "$$pids" ]; then kill -9 $$pids 2>/dev/null || true; fi; \
		fi; \
	done

stop-triad:
	@for port in 7700 8011 8012 8013 8501; do \
		pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null); \
		if [ -n "$$pids" ]; then \
			echo "Stopping listener on port $$port ($$pids)"; \
			kill $$pids 2>/dev/null || true; \
			sleep 0.5; \
			pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null); \
			if [ -n "$$pids" ]; then kill -9 $$pids 2>/dev/null || true; fi; \
		fi; \
	done

stop-brief:
	@for port in 7700 8021 8022 8023; do \
		pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null); \
		if [ -n "$$pids" ]; then \
			echo "Stopping listener on port $$port ($$pids)"; \
			kill $$pids 2>/dev/null || true; \
			sleep 0.5; \
			pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null); \
			if [ -n "$$pids" ]; then kill -9 $$pids 2>/dev/null || true; fi; \
		fi; \
	done

db-clear:
	$(PYTHON) scripts/db_clear.py

db-reseed:
	$(PYTHON) scripts/db_reseed.py

db-reset: db-clear db-reseed
