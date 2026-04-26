#!/bin/bash
set -e

# Configuration
REPO_URL="https://github.com/ketankr9/product-research.git"
INSTALL_DIR="product-research"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Installing Product Research Agent...${NC}"

# Check for git
if ! command -v git &> /dev/null; then
    echo -e "${RED}Error: git is not installed.${NC}"
    exit 1
fi

# Clone repository
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${BLUE}Cloning repository into $INSTALL_DIR...${NC}"
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
else
    echo -e "${GREEN}Directory $INSTALL_DIR already exists. Entering...${NC}"
    cd "$INSTALL_DIR"
    # Try to update if it's a git repo
    if [ -d ".git" ]; then
        git pull
    fi
fi

# Check for Python 3.11+
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found. Please install Python 3.11 or higher.${NC}"
    exit 1
fi

if ! python3 -c "import sys; exit(0) if sys.version_info >= (3, 11) else exit(1)"; then
    echo -e "${RED}Error: Python 3.11 or higher is required.${NC}"
    exit 1
fi

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo -e "${BLUE}Creating virtual environment...${NC}"
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
echo -e "${BLUE}Installing dependencies...${NC}"
pip install --upgrade pip
pip install -e .

# Setup .env and Global Config
CONFIG_DIR="$HOME/.product_research"
mkdir -p "$CONFIG_DIR"

if [ -f ".env.example" ]; then
    if [ ! -f ".env" ]; then
        echo -e "${BLUE}Setting up local .env file...${NC}"
        cp .env.example .env
    fi
    
    if [ ! -f "$CONFIG_DIR/.env" ]; then
        echo -e "${BLUE}Setting up global config at $CONFIG_DIR/.env...${NC}"
        cp .env.example "$CONFIG_DIR/.env"
        echo -e "${GREEN}Global config created. You can also set API keys here to use them across different projects.${NC}"
    fi
fi

# Check for API Keys
if [ -z "$TAVILY_API_KEY" ]; then
    echo -e "${RED}Warning: TAVILY_API_KEY is not set, web search will not work. Only Amazon search will be available.${NC}"
fi

echo -e "\n${GREEN}Installation complete!${NC}"
echo -e "To get started:"
echo -e "  1. ${BLUE}cd $INSTALL_DIR${NC}"
echo -e "  2. ${BLUE}Add API keys to ~/.product_research/.env or the local .env file${NC}"
echo -e "  3. ${BLUE}./research.sh \"best laptop for coding\"${NC}"
echo -e "  4. ${BLUE}./chat.sh${NC}"
