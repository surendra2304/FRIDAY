# ==============================================================================
# FRIDAY Core Production Container
# Modernized for Oracle Cloud Always Free & Unified Docker Mesh (friday_mesh)
# Target: https://friday-universe.duckdns.org
# ==============================================================================

# Stage 1: Build Next.js Command Center HUD
FROM node:22-alpine AS ui-build
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# Stage 2: Production Python 3.11 Runtime
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

# Security Hardening: Non-root user appuser (UID 1000)
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app /app/data /app/logs && \
    chown -R appuser:appuser /app

WORKDIR /app

# Copy project specifications, requirements, and source code
COPY pyproject.toml README.md requirements.txt ./
COPY src/ ./src/
COPY --from=ui-build /ui/out/ /app/ui/
ENV FRIDAY_UI_DIR=/app/ui

# Install dependencies cleanly
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose internal mesh gateway port
EXPOSE 10000

# Native Docker Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:10000/health || exit 1

# Start FRIDAY FastAPI/MCP server listening on Container Port 10000 (exec forwards PID 1 signals)
CMD ["sh", "-c", "exec uvicorn friday.api.server:app --host 0.0.0.0 --port ${PORT:-10000}"]
