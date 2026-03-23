# =============================================================================
# Self-Healing Kubernetes Platform - Makefile
# =============================================================================
# Quick Start:
#   make demo           - Run the full demo (recommended!)
#   make demo-infra     - Set up infrastructure only (for manual scenario testing)
#   make demo-clean     - Clean up demo cluster
# =============================================================================

.PHONY: help demo demo-infra demo-clean install test lint format docker-build clean

# Default target - show help
help:
	@echo ""
	@echo "🚀 Self-Healing Kubernetes Platform"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Quick Start:"
	@echo "  make demo        Run full demo (creates KIND cluster, deploys, shows healing)"
	@echo "  make demo-infra  Set up infrastructure only (no auto-deploy scenarios)"
	@echo "  make demo-clean  Delete demo cluster"
	@echo ""
	@echo "Development:"
	@echo "  make install     Install Python dependencies"
	@echo "  make test        Run unit tests"
	@echo "  make lint        Run linters"
	@echo "  make format      Format code"
	@echo ""
	@echo "Build:"
	@echo "  make docker-build  Build Docker image"
	@echo "  make clean         Clean build artifacts"
	@echo ""
	@echo "For REAL AI (optional, free):"
	@echo "  1. Install Ollama: https://ollama.ai"
	@echo "  2. Run: ollama pull llama3"
	@echo "  3. Run: ollama serve"
	@echo "  4. Run: make demo"
	@echo ""

# =============================================================================
# 🎯 DEMO - Main Entry Point!
# =============================================================================

demo:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh

demo-infra:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh infra-only

demo-clean:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh clean

# =============================================================================
# Development
# =============================================================================

install:
	pip install -r requirements.txt
	pip install -e .

test:
	pytest tests/unit/ -v

lint:
	flake8 operator/ --max-line-length=100 || true
	mypy operator/ --ignore-missing-imports || true

format:
	black operator/ tests/ || true
	isort operator/ tests/ || true

# =============================================================================
# Build
# =============================================================================

docker-build:
	docker build -t self-healing-operator:latest .

# =============================================================================
# Cleanup
# =============================================================================

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .pytest_cache/ .mypy_cache/ 2>/dev/null || true
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build/ dist/ .pytest_cache/ .mypy_cache/
