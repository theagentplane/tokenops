.PHONY: install research-server summarize-server ui run dev stop

PYTHON ?= python3
export PYTHONPATH := src$(if $(PYTHONPATH),:$(PYTHONPATH),)
export TOKENOPS_CONFIG ?= src/tokenops/config/default.yaml

install:
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	$(PYTHON) -m pip install -r requirements.txt

research-server:
	$(PYTHON) -m tokenops.servers.research

summarize-server:
	$(PYTHON) -m tokenops.servers.summarize

ui:
	streamlit run src/tokenops/ui/app.py --server.port 8501

run:
	$(PYTHON) run.py

stop:
	@for port in 8001 8002 8501; do \
		pids=$$(lsof -ti :$$port 2>/dev/null); \
		if [ -n "$$pids" ]; then echo "Stopping port $$port ($$pids)"; kill $$pids 2>/dev/null || true; fi; \
	done

dev: run
