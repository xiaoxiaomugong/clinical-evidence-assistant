.PHONY: install run test smoke eval verify-pmids index-pdfs

install:
	python3 -m pip install -r requirements.txt

run:
	PYTHONPATH=src:. streamlit run app.py

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
