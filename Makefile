.PHONY: install install-tool run run-tool test smoke eval verify-pmids index-pdfs

install:
	python3 -m pip install -r requirements.txt

install-tool:
	python3 -m pip install -e '.[mcp]'

run:
	PYTHONPATH=src:. streamlit run app.py

run-tool:
	PYTHONPATH=src:. python3 -m evidence_assistant.mcp_server

test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. pytest -q

smoke:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python3 scripts/smoke_test.py

eval:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python3 eval/run_eval.py --mode hybrid

verify-pmids:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python3 scripts/verify_pmids.py --strict

index-pdfs:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python3 scripts/index_pdf_collection.py
