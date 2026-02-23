#!/bin/bash

# Azure Tools Installation Script for BADI Oerlikon Project
# This script installs all necessary Azure tools and dependencies

set -e

echo "=========================================="
echo "Azure Tools Installation Script"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running with sudo (for apt installations)
if [[ $EUID -ne 0 ]]; then
   echo -e "${YELLOW}Note: Some installations require sudo. You may be prompted for your password.${NC}"
fi

echo ""
echo -e "${BLUE}Step 1: Verify Azure CLI Installation${NC}"
if command -v az &> /dev/null; then
    AZ_VERSION=$(az --version | head -1)
    echo -e "${GREEN}✓ Azure CLI already installed: $AZ_VERSION${NC}"
else
    echo "Installing Azure CLI..."
    sudo apt-get update
    sudo apt-get install -y azure-cli
    echo -e "${GREEN}✓ Azure CLI installed${NC}"
fi

echo ""
echo -e "${BLUE}Step 2: Install Node.js and npm${NC}"
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    NPM_VERSION=$(npm --version)
    echo -e "${GREEN}✓ Node.js already installed: $NODE_VERSION${NC}"
    echo -e "${GREEN}✓ npm already installed: $NPM_VERSION${NC}"
else
    echo "Installing Node.js and npm..."
    sudo apt-get update
    sudo apt-get install -y nodejs npm
    echo -e "${GREEN}✓ Node.js and npm installed${NC}"
fi

echo ""
echo -e "${BLUE}Step 3: Install Azure Functions Core Tools${NC}"
if command -v func &> /dev/null; then
    FUNC_VERSION=$(func --version)
    echo -e "${GREEN}✓ Azure Functions Core Tools already installed: $FUNC_VERSION${NC}"
else
    echo "Installing Azure Functions Core Tools via npm..."
    sudo npm install -g azure-functions-core-tools@4 --unsafe-perm
    echo -e "${GREEN}✓ Azure Functions Core Tools installed${NC}"
fi

echo ""
echo -e "${BLUE}Step 4: Install Git (if not present)${NC}"
if command -v git &> /dev/null; then
    GIT_VERSION=$(git --version)
    echo -e "${GREEN}✓ Git already installed: $GIT_VERSION${NC}"
else
    echo "Installing Git..."
    sudo apt-get update
    sudo apt-get install -y git
    echo -e "${GREEN}✓ Git installed${NC}"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}Installation Complete!${NC}"
echo "=========================================="
echo ""

echo "Installed Tools:"
echo ""
az --version | head -1 && echo "  ✓ Azure CLI"
node --version && echo "  ✓ Node.js"
npm --version && echo "  ✓ npm"
func --version && echo "  ✓ Azure Functions Core Tools"
git --version && echo "  ✓ Git"

echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "1. Log in to Azure:"
echo "   ${YELLOW}az login${NC}"
echo ""
echo "2. Set your subscription:"
echo "   ${YELLOW}az account set --subscription cc569079-9e12-412d-8dfb-a5d60a028f75${NC}"
echo ""
echo "3. Test Azure Functions locally:"
echo "   Collector: ${YELLOW}cd src/collector && func start${NC}"
echo "   API:       ${YELLOW}cd src/api && func start${NC}"
echo ""
echo "4. Deploy to Azure:"
echo "   Read: QUICKSTART.md"
echo ""
echo "=========================================="
