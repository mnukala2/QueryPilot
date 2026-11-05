.PHONY: install data test eval-offline eval api ui mcp docker

install:
	pip install -r requirements-dev.txt

data:
	python -m querypilot.data_gen --path data/warehouse.duckdb

test:
	pytest --cov=querypilot --cov-report=term-missing

eval-offline:
	python eval/offline_eval.py --json results/offline.json

eval:            ## needs an LLM key in .env
	python eval/run_eval.py --json results/llm.json

eval-ablation:   ## same benchmark with the full schema in every prompt
	python eval/run_eval.py --no-retrieval --json results/llm_no_retrieval.json

api:
	uvicorn querypilot.api:app --reload --port 8000

ui:
	streamlit run querypilot/ui.py

mcp:
	python -m querypilot.mcp_server

docker:
	docker compose up --build
