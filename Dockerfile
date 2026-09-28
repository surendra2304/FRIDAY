# ==============================================================================
# FRIDAY command center UI and FastAPI/MCP service (Render)
# ==============================================================================
FROM node:22-alpine AS ui-build
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

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

# Copy project specifications and source code
COPY pyproject.toml README.md requirements.txt* ./
COPY src/ ./src/
COPY --from=ui-build /ui/out/ /app/ui/
ENV FRIDAY_UI_DIR=/app/ui

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Ensure persistent data and logs directories exist
RUN mkdir -p /app/data /app/logs

# Cloud healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-10000}/health || exit 1

EXPOSE 10000

# Start FRIDAY FastAPI/MCP server listening on Render's assigned $PORT
CMD ["sh", "-c", "uvicorn friday.api.server:app --host 0.0.0.0 --port ${PORT:-10000}"]
