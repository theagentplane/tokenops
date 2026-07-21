.PHONY: install research-server summarize-server control-plane ui bench-ui run dev stop db-clear db-reseed db-reset

PYTHON ?= python3
export PYTHONPATH := src:.$(if $(PYTHONPATH),:$(PYTHONPATH),)
export TOKENOPS_CONFIG ?= src/tokenops/config/default.yaml

install:
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	$(PYTHON) -m pip install -r requirements.txt

control-plane:
	$(PYTHON) -m tokenops.server

research-server:
	$(PYTHON) -m bench.servers.research

summarize-server:
	$(PYTHON) -m bench.servers.summarize

# Plane-side product UI (Admin + Dashboard). Not agent-local.
ui:
	streamlit run src/tokenops/ui/app.py --server.port 8501

# Bench-only Chat + Simulator (also embeds Admin/Dashboard for local demos).
bench-ui:
	streamlit run bench/ui/app.py --server.port 8501

run: stop
	$(PYTHON) run.py

stop:
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

dev: run

db-clear:
	$(PYTHON) scripts/db_clear.py

db-reseed:
	$(PYTHON) scripts/db_reseed.py

db-reset: db-clear db-reseed
