#!/bin/bash
# Run script for Product Research Agent
# Usage: ./research.sh [options]

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtual environment
if [ -d "$SCRIPT_DIR/.venv" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
else
    echo "Error: Virtual environment not found at $SCRIPT_DIR/.venv"
    echo "Please create it with: python3 -m venv .venv"
    exit 1
fi

# Check if API keys are set
if [ -z "$TAVILY_API_KEY" ] && [ -z "$(grep -s '^TAVILY_API_KEY=' $SCRIPT_DIR/.env 2>/dev/null)" ]; then
    echo "Warning: TAVILY_API_KEY is not set, only amazon search will work and general search will not work."
    echo "Set it with: export TAVILY_API_KEY=your_key"
    echo "Or add it to: $SCRIPT_DIR/.env"
    echo ""
fi

if [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$GOOGLE_API_KEY" ]; then
    ANTHROPIC_IN_ENV=$(grep -s '^ANTHROPIC_API_KEY=' $SCRIPT_DIR/.env 2>/dev/null)
    GOOGLE_IN_ENV=$(grep -s '^GOOGLE_API_KEY=' $SCRIPT_DIR/.env 2>/dev/null)
    if [ -z "$ANTHROPIC_IN_ENV" ] && [ -z "$GOOGLE_IN_ENV" ]; then
        echo "Warning: Neither ANTHROPIC_API_KEY nor GOOGLE_API_KEY is set"
        echo "Set one with: export ANTHROPIC_API_KEY=your_key"
        echo "Or add it to: $SCRIPT_DIR/.env"
        echo ""
    fi
fi

# Run the CLI with any passed arguments
cd "$SCRIPT_DIR"
python -m product_research.cli research "$@"
