FROM python:3.11-slim

LABEL org.opencontainers.image.title="Self-Healing Kubernetes Operator" \
      org.opencontainers.image.description="AI-powered Kubernetes operator for automatic issue remediation" \
      org.opencontainers.image.authors="Your Name"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy operator code to a non-conflicting path
COPY operator/ /app/healing_operator/

# Create non-root user (avoid conflict with existing 'operator' group)
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Run the operator (using module path to avoid name conflict with Python's operator module)
CMD ["python", "-m", "healing_operator.main"]
