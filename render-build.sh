#!/usr/bin/env bash
# ==============================================================================
# Render Native Python Build Script for FRIDAY
# Use this build command on Render when using the Native Python environment:
# Build Command: ./render-build.sh
# Start Command: uvicorn friday.api.server:app --host 0.0.0.0 --port $PORT
# ==============================================================================
set -o errexit

echo "==> Upgrading pip..."
pip install --upgrade pip

echo "==> Installing FRIDAY dependencies..."
pip install -e .

echo "==> Ensuring data and log directories..."
mkdir -p data logs

echo "==> FRIDAY build complete!"
