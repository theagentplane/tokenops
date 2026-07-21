.PHONY: install control-plane ui run stop db-clear db-reseed db-reset

PYTHON ?= python3
export PYTHONPATH := src$(if $(PYTHONPATH),:$(PYTHONPATH),)
export TOKENOPS_CONFIG ?= src/tokenops/config/default.yaml

install:
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	$(PYTHON) -m pip install -e ".[dev]"

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

db-clear:
	$(PYTHON) scripts/db_clear.py

db-reseed:
	$(PYTHON) scripts/db_reseed.py

db-reset: db-clear db-reseed
