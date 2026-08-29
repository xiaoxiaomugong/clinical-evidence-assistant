.PHONY: install install-ui install-tool run run-ui run-tool package-check test smoke eval verify-pmids index-pdfs

install:
	python3 -m pip install -r requirements.txt

install-ui:
	python3 -m pip install -e '.[ui]'

install-tool:
	python3 -m pip install -e '.[mcp]'

run:
	PYTHONPATH=src:. streamlit run app.py

run-ui:
	PYTHONPATH=src:. python3 -m evidence_assistant.desktop

run-tool:
	PYTHONPATH=src:. python3 -m evidence_assistant.mcp_server

package-check:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python3 -m evidence_assistant.desktop --check

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
