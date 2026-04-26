#!/bin/bash
# Chat script for Product Research Agent
# Usage: ./chat.sh [options]

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.product_research"
CONFIG_FILE="$CONFIG_DIR/.env"

# Load environment variables in order of priority:
# 1. Existing environment variables (already set)
# 2. Local .env file in script directory
# 3. Global config file in ~/.product_research/.env

if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

if [ -f "$CONFIG_FILE" ]; then
    # Only export if not already set
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ ! "$line" =~ ^# ]] && [[ "$line" =~ = ]]; then
            key=$(echo "$line" | cut -d '=' -f 1)
            if [ -z "${!key}" ]; then
                export "$line"
            fi
        fi
    done < "$CONFIG_FILE"
fi

# Activate virtual environment
if [ -d "$SCRIPT_DIR/.venv" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
else
    echo "Error: Virtual environment not found at $SCRIPT_DIR/.venv"
    echo "Please create it with: python3 -m venv .venv"
    exit 1
fi

# Run the CLI with any passed arguments
cd "$SCRIPT_DIR"
python -m product_research.cli chat "$@"
