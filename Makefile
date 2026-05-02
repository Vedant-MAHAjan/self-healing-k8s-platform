# =============================================================================
# Self-Healing Kubernetes Platform - Makefile
# =============================================================================
# Quick Start (zero cost, no API keys needed):
#   make demo               - Full demo: KIND cluster + operator + crash scenario
#   make demo-infra         - Cluster + operator only (deploy scenarios manually)
#   make demo-autonomous    - Show full autonomous control plane in action
#   make demo-scenario SCENARIO=oom-killed  - Deploy a single named scenario
#   make demo-watch         - Tail filtered operator logs (decisions, scheduler, breaker)
#   make demo-state         - Show pods, incidents, and job status
#   make demo-clean         - Delete demo cluster
#
# AI providers (no API keys ever required):
#   Default: Ollama (local LLM, free) → auto-falls-back to Mock (built-in, no setup)
# =============================================================================

.PHONY: help demo demo-infra demo-autonomous demo-scenario demo-watch demo-state \
        demo-clean install test lint format docker-build clean

# Python interpreter — prefer activated venv, fall back to python3.11, then python3
PYTHON ?= $(shell command -v python3.11 2>/dev/null || command -v python3 2>/dev/null || echo python3)

SCENARIO ?= oom-killed

# Default target - show help
help:
	@echo ""
	@echo "🚀 Self-Healing Kubernetes Platform (Zero Cost)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Demo (no API keys required):"
	@echo "  make demo                            Full demo — cluster, operator, crash scenario"
	@echo "  make demo-infra                      Cluster + operator only"
	@echo "  make demo-autonomous                 Show full autonomous pipeline in action"
	@echo "  make demo-scenario SCENARIO=<name>   Deploy one scenario (default: oom-killed)"
	@echo "  make demo-watch                      Tail filtered operator logs"
	@echo "  make demo-state                      Show pod + job status"
	@echo "  make demo-clean                      Delete demo cluster"
	@echo ""
	@echo "  Scenarios: oom-killed, crash-loop, memory-leak, image-pull-error"
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
	@echo "Optional free AI upgrade:"
	@echo "  brew install ollama && ollama pull llama3 && ollama serve"
	@echo "  (make demo auto-detects Ollama — no config change needed)"
	@echo ""

# =============================================================================
# 🎯 DEMO - Main Entry Points
# =============================================================================

demo:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh

demo-infra:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh infra-only

demo-autonomous:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh autonomous

demo-scenario:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh scenario $(SCENARIO)

demo-watch:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh watch

demo-state:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh state

demo-clean:
	@chmod +x scripts/demo.sh
	@./scripts/demo.sh clean

# =============================================================================
# Development
# =============================================================================

install:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

test:
	$(PYTHON) -m pytest tests/unit/ -v

lint:
	$(PYTHON) -m flake8 k8s_operator/ --max-line-length=100 || true
	$(PYTHON) -m mypy k8s_operator/ --ignore-missing-imports || true

format:
	$(PYTHON) -m black k8s_operator/ tests/ || true
	$(PYTHON) -m isort k8s_operator/ tests/ || true

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
