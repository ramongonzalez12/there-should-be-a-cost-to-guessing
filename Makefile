.PHONY: help install test lint census properness power site essay-page essay-data ci clean

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

install:            ## editable install with dev extras
	pip install -e ".[dev]"

test:               ## unit tests (no network, no key)
	pytest

lint:
	ruff check src tests scripts

census:             ## the 1.09M-response abstention sweep (~20 min, free)
	python scripts/census.py

properness:         ## numerical check that the scoring rules do what they claim
	python scripts/properness.py

power:              ## sample sizes for both experimental designs
	python scripts/power.py

site:               ## render site/below-zero/index.html from committed CSVs
	python scripts/build_site.py

essay-page:         ## render essay.html, the superseded v2.7 essay (August 2026), from committed CSVs
	python scripts/build_essay_page.py

essay-data:         ## the essay from graded rows: tables, figure CSVs, key numbers; diff against data/essay (no key)
	python scripts/essay_data_step.py --check

ci:                 ## what CI runs: lint, unit, site and essay rebuilds, essay data
	ruff check src tests scripts
	pytest -q
	python scripts/build_site.py
	python scripts/build_essay_page.py
	git diff --exit-code -- site/below-zero
	python scripts/essay_data_step.py --check

clean:
	rm -rf build dist *.egg-info .pytest_cache src/**/__pycache__
