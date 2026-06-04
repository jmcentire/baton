.PHONY: install dev test lint clean

PYTHON ?= python3
PYTHONPATH ?= src

install:
	$(PYTHON) -m pip install -e .

dev:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest

lint:
	$(PYTHON) -m py_compile src/baton/*.py

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
