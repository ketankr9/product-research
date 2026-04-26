# DeepAgents: Product Research

A powerful product research agent built with LangChain and Tavily.

## Installation

You can install the Product Research Agent by running the following command:

```bash
curl -LsSf https://raw.githubusercontent.com/ketankr9/product-research/master/install.sh | bash
```

Alternatively, you can set it up manually:

1. **Setup Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   # Fill in your API keys in .env file.
   if [ ! -f .env ]; then
       cp .env.example .env
   fi
   ```

2. **Run Research**:
   ```bash
   # Single research query
   ./research.sh "best smartphone under 30k"

   # With local model.
   ./research.sh --model-provider="local" "best smartphone under 30k"

   # Interactive chat mode
   python -m product_research.cli chat
   ```

## Key Features
- **Interactive Chat**: maintain context with follow-up questions
- **Multi-Source**: Web search via Tavily & Amazon.in extraction
- **Review Analysis**: Deep sentiment and quality analysis
- **Comprehensive Reports**: Detailed markdown results with citations
