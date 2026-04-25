# DeepAgents: Product Research

A powerful product research agent built with LangChain and Tavily.

## Quick Start

1. **Setup Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   # Create a .env file and add your API keys
   ```

2. **Run Research**:
   ```bash
   # Single research query
   ./research.sh "best smartphone under 30k"

   # Interactive chat mode
   python -m product_research.cli chat
   ```

## Key Features
- **Interactive Chat**: maintain context with follow-up questions
- **Multi-Source**: Web search via Tavily & Amazon.in extraction
- **Review Analysis**: Deep sentiment and quality analysis
- **Comprehensive Reports**: Detailed markdown results with citations
