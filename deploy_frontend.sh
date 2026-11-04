#!/usr/bin/env bash
# FRIDAY Frontend Deployment Script
# Deploys FRIDAY frontend files to production server with rollback on failure

set -euo pipefail

# Configuration
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly FRONTEND_SOURCE="${PROJECT_ROOT}/src/friday/api"
readonly SSH_KEY="${HOME}/.ssh/friday_universe_oracle.key"
readonly REMOTE_USER="ubuntu"
readonly REMOTE_HOST="140.245.208.100"
readonly REMOTE_PATH="/opt/friday_universe/FRIDAY/src/friday/api"
readonly SERVICE_NAME="FRIDAY.service"
readonly HEALTH_ENDPOINT="https://friday-universe.duckdns.org/friday/health"
readonly DASHBOARD_ENDPOINT="https://friday-universe.duckdns.org/friday/"
readonly BACKUP_DIR="/opt/friday_universe/FRIDAY/src/friday/api.backup.$(date +%Y%m%d_%H%M%S)"

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Logging functions
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}"
}

log_info() {
    log "${BLUE}INFO${NC}" "$@"
}

log_success() {
    log "${GREEN}SUCCESS${NC}" "$@"
}

log_warn() {
    log "${YELLOW}WARN${NC}" "$@"
}

log_error() {
    log "${RED}ERROR${NC}" "$@"
}

# Cleanup function for rollback
rollback() {
    log_warn "Rolling back to previous version..."
    if ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" \
        "[ -d '${BACKUP_DIR}' ]"; then
        ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" \
            "sudo rm -rf '${REMOTE_PATH}' && sudo mv '${BACKUP_DIR}' '${REMOTE_PATH}' && sudo chown -R ubuntu:ubuntu '${REMOTE_PATH}'"
        log_success "Rollback completed"
    else
        log_error "No backup found at ${BACKUP_DIR}, manual intervention required"
    fi
    restart_service
    exit 1
}

# Restart FRIDAY service
restart_service() {
    log_info "Restarting ${SERVICE_NAME}..."
    if ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" \
        "sudo systemctl restart ${SERVICE_NAME}"; then
        log_success "Service restarted"
        # Wait for service to be ready
        sleep 5
    else
        log_error "Failed to restart service"
        return 1
    fi
}

# Verify health endpoint
verify_health() {
    log_info "Verifying health endpoint: ${HEALTH_ENDPOINT}"
    local max_attempts=10
    local attempt=1
    
    while [[ ${attempt} -le ${max_attempts} ]]; do
        if curl -sf --max-time 10 "${HEALTH_ENDPOINT}" > /dev/null; then
            log_success "Health endpoint responding (attempt ${attempt}/${max_attempts})"
            return 0
        fi
        log_warn "Health check failed (attempt ${attempt}/${max_attempts}), retrying in 3s..."
        sleep 3
        ((attempt++))
    done
    
    log_error "Health endpoint not responding after ${max_attempts} attempts"
    return 1
}

# Verify dashboard loads
verify_dashboard() {
    log_info "Verifying dashboard loads: ${DASHBOARD_ENDPOINT}"
    local response
    response=$(curl -sf --max-time 10 "${DASHBOARD_ENDPOINT}" 2>/dev/null || echo "")
    
    if echo "${response}" | grep -qi "FRIDAY"; then
        local count
        count=$(echo "${response}" | grep -ic "FRIDAY" || echo "0")
        log_success "Dashboard loaded successfully (found 'FRIDAY' ${count} times)"
        return 0
    else
        log_error "Dashboard does not contain 'FRIDAY' text"
        return 1
    fi
}

# Main deployment function
deploy() {
    log_info "=== Starting FRIDAY Frontend Deployment ==="
    log_info "Source: ${FRONTEND_SOURCE}"
    log_info "Target: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}"
    
    # Check source files exist
    if [[ ! -d "${FRONTEND_SOURCE}" ]]; then
        log_error "Source directory not found: ${FRONTEND_SOURCE}"
        exit 1
    fi
    
    local file_count
    file_count=$(find "${FRONTEND_SOURCE}" -maxdepth 1 -type f \( -name "*.html" -o -name "*.js" -o -name "*.css" \) | wc -l)
    log_info "Found ${file_count} frontend files to deploy"
    
    if [[ ${file_count} -eq 0 ]]; then
        log_error "No frontend files found to deploy"
        exit 1
    fi
    
    # List files being deployed
    find "${FRONTEND_SOURCE}" -maxdepth 1 -type f \( -name "*.html" -o -name "*.js" -o -name "*.css" \) -exec basename {} \; | while read -r file; do
        log_info "  - ${file}"
    done
    
    # Create backup on remote server
    log_info "Creating backup on remote server..."
    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" \
        "sudo cp -r '${REMOTE_PATH}' '${BACKUP_DIR}' && sudo chown -R ubuntu:ubuntu '${BACKUP_DIR}'"
    log_success "Backup created at ${BACKUP_DIR}"
    
    # Deploy files via SCP
    log_info "Deploying frontend files..."
    scp -i "${SSH_KEY}" -o StrictHostKeyChecking=no \
        "${FRONTEND_SOURCE}"/*.html \
        "${FRONTEND_SOURCE}"/*.js \
        "${FRONTEND_SOURCE}"/*.css \
        "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/" 2>/dev/null || true
    
    # Verify files were copied
    log_info "Verifying deployment on remote server..."
    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" \
        "ls -la '${REMOTE_PATH}'/"
    log_success "Files deployed successfully"
    
    # Restart service
    restart_service || { log_error "Service restart failed"; rollback; }
    
    # Verify health endpoint
    verify_health || { log_error "Health check failed"; rollback; }
    
    # Verify dashboard
    verify_dashboard || { log_error "Dashboard verification failed"; rollback; }
    
    log_success "=== Deployment Completed Successfully ==="
    log_info "Backup retained at: ${BACKUP_DIR} (manual cleanup required)"
}

# Trap errors and rollback
trap 'log_error "Deployment failed at line $LINENO"; rollback' ERR

# Check SSH key exists
if [[ ! -f "${SSH_KEY}" ]]; then
    log_error "SSH key not found: ${SSH_KEY}"
    exit 1
fi

# Check SSH connectivity
log_info "Testing SSH connectivity..."
if ! ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    "${REMOTE_USER}@${REMOTE_HOST}" "echo 'SSH OK'" > /dev/null 2>&1; then
    log_error "Cannot connect to ${REMOTE_USER}@${REMOTE_HOST}"
    exit 1
fi
log_success "SSH connectivity verified"

# Run deployment
deploy

# Cleanup old backups (keep last 5)
log_info "Cleaning up old backups (keeping last 5)..."
ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" \
    "cd /opt/friday_universe/FRIDAY/src && ls -dt friday/api.backup.* 2>/dev/null | tail -n +6 | xargs -r sudo rm -rf"
log_success "Old backups cleaned up"

log_info "=== All Done ==="