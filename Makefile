.PHONY: bootstrap web check analyze builder

bootstrap:
	python3 -m pip install -r requirements.txt

web:
	python3 -m uvicorn app.web:app --reload --port 8000

check:
	python3 scripts/doctor.py && python3 -m pytest -q

analyze:
	python3 scripts/analyze_template.py --template "$(TEMPLATE)"

builder:
	python3 scripts/run_template_builder.py
