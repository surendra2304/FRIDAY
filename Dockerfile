# ==============================================================================
# FRIDAY Holographic Core & FastMCP Server - Cloud Container (Render)
# ==============================================================================
FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr and writing bytecode
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000 \
    HOST=0.0.0.0 \
    FRIDAY_ENV=production

# Install essential system build dependencies and curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specifications first for Docker layer caching
COPY pyproject.toml README.md requirements.txt* ./

# Install dependencies (platform markers in pyproject.toml automatically exclude win32-only libraries)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Copy project source code and assets
COPY src/ ./src/
COPY data/ ./data/

# Ensure persistent data and logs directories exist
RUN mkdir -p /app/data /app/logs

# Cloud healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-10000}/health || exit 1

EXPOSE 10000

# Start FRIDAY FastAPI/MCP server listening on Render's assigned $PORT
CMD ["sh", "-c", "uvicorn friday.api.server:app --host 0.0.0.0 --port ${PORT:-10000}"]
