.PHONY: test coverage clean lint build

build:
	pip install -e .

test:
	pytest tests/

coverage:
	pytest tests/ --cov=src/ailuropoda --cov-report=json --cov-report=html:coverage

lint:
	ruff check .

clean:
	rm -rf .coverage htmlcov coverage .pytest_cache build dist *.egg-info
