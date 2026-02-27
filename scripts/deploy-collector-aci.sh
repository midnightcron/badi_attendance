#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# Deploy the ACI collector (dev environment)
#
# Prerequisites:
#   - az CLI logged in
#   - Docker running
#   - Terraform initialized in azure/collector-aci/
#
# Usage:
#   ./scripts/deploy-collector-aci.sh          # full deploy
#   ./scripts/deploy-collector-aci.sh --image   # rebuild & push image only
#   ./scripts/deploy-collector-aci.sh --infra   # terraform apply only
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$ROOT_DIR/azure/collector-aci"
SRC_DIR="$ROOT_DIR/src/collector-aci"
IMAGE_NAME="badi-collector"
IMAGE_TAG="${IMAGE_TAG:-latest}"

# ── Colours ───────────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}▸${NC} $*"; }
warn()  { echo -e "${YELLOW}▸${NC} $*"; }
header(){ echo -e "\n${BOLD}═══ $* ═══${NC}"; }

# ── Parse flags ───────────────────────────────────────────────────
DO_IMAGE=true
DO_INFRA=true
if [[ "${1:-}" == "--image" ]]; then DO_INFRA=false; fi
if [[ "${1:-}" == "--infra" ]]; then DO_IMAGE=false; fi

# ── Step 1: Terraform (creates RG, storage, ACR, ACI) ────────────
if $DO_INFRA; then
    header "Terraform Init & Apply"
    cd "$TF_DIR"
    terraform init -upgrade
    terraform apply -auto-approve
    cd "$ROOT_DIR"
fi

# ── Step 2: Get ACR login server from Terraform outputs ──────────
header "Reading Terraform outputs"
ACR_LOGIN_SERVER=$(cd "$TF_DIR" && terraform output -raw acr_login_server)
info "ACR: $ACR_LOGIN_SERVER"

# ── Step 3: Docker build & push ──────────────────────────────────
if $DO_IMAGE; then
    header "Docker build"
    docker build -t "$IMAGE_NAME:$IMAGE_TAG" "$SRC_DIR"

    header "Docker push to ACR"
    az acr login --name "${ACR_LOGIN_SERVER%%.*}"
    docker tag "$IMAGE_NAME:$IMAGE_TAG" "$ACR_LOGIN_SERVER/$IMAGE_NAME:$IMAGE_TAG"
    docker push "$ACR_LOGIN_SERVER/$IMAGE_NAME:$IMAGE_TAG"
    info "Pushed $ACR_LOGIN_SERVER/$IMAGE_NAME:$IMAGE_TAG"
fi

# ── Step 4: Restart ACI to pick up new image ─────────────────────
header "Restarting ACI container"
RG_NAME=$(cd "$TF_DIR" && terraform output -raw resource_group_name)
CG_NAME=$(cd "$TF_DIR" && terraform output -raw container_group_name)
az container restart --resource-group "$RG_NAME" --name "$CG_NAME"
info "Container restarted"

# ── Done ──────────────────────────────────────────────────────────
header "Deployment complete"
info "View logs:  az container logs -g $RG_NAME -n $CG_NAME --follow"
info "Check data: az storage blob list --account-name $(cd "$TF_DIR" && terraform output -raw storage_account_name) -c occupancy-data --output table"
