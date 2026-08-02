.PHONY: help install dev doctor test lint fmt clean

help:  ## Show this help
	@echo "voxpane — make targets:"
	@echo "  make install   editable install into the current environment"
	@echo "  make dev       editable install with dev + daemon extras"
	@echo "  make doctor    run voxpane doctor"
	@echo "  make test      run the test suite"
	@echo "  make lint      ruff check"
	@echo "  make fmt       ruff format"

install:  ## Editable install
	uv pip install -e . 2>/dev/null || pip install -e .

dev:  ## Editable install with dev + daemon extras
	uv pip install -e '.[dev,daemon]' 2>/dev/null || pip install -e '.[dev,daemon]'

doctor:  ## Run the environment check
	voxpane doctor

test:  ## Run tests
	pytest

lint:  ## Lint
	ruff check src tests

fmt:  ## Format
	ruff format src tests

clean:  ## Remove build/test artefacts
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
