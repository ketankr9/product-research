"""General Product Research Agent - Supports Amazon and Web research."""

import os
from datetime import datetime
from pathlib import Path
from typing import Generator, Dict, Any, Literal

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, ToolMessage, AIMessageChunk

from deepagents import create_deep_agent

from .tools import amazon_direct_search, fetch_product_info, fetch_reviews, tavily_search

# Load environment variables from .env file and bash environment
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# initialization logic moved to cli.py

def merge_dicts(base: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge dictionaries by summing numeric values."""
    for k, v in new.items():
        if isinstance(v, (int, float)):
            base[k] = base.get(k, 0) + v
        elif isinstance(v, dict) and k in base and isinstance(base[k], dict):
            merge_dicts(base[k], v)
        elif isinstance(v, dict):
            base[k] = v.copy()
            # If the new dict has numeric values, make sure they are preserved
            # merge_dicts will be called on this copy if another dict with same key appears
        else:
            base[k] = v
    return base

def _init_llm(model: str, model_provider: str):
    """Initialize a chat model."""
    if not model:
        return None

    # LangChain recognizes 'google_genai' as the provider for Google Gemini models.
    if model_provider == 'google':
        model_provider = "google_genai"

    if model_provider == "local":
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("LOCAL_URL", "http://localhost:1234/v1")
        return ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key="local"
        )
    else:
        return init_chat_model(model=model, model_provider=model_provider)

PRODUCT_RESEARCHER_PROMPT = """You are a product research analyst. You find, compare, and recommend products using Amazon.in and web sources.

# Research Scope
- General queries (e.g. "best budget laptops"): research exactly {item_limit} products.
- Specific model queries (e.g. "realme GT 7T"): research at most 3 products.

# Phase 1 — Discovery
Use these tools to find candidates:

**amazon_direct_search(query, url_params, max_results)**
- `query`: Extract the core product noun/keyword only. Never pass the user's raw sentence.
  ✓ "smartphone"  ✗ "best smartphone under 20000"
- `url_params`: List of filter strings, each prefixed with `&` as amazon params. Example: ["&high-price=20000"]

**tavily_search(query)**
- Use descriptive queries with "reviews" appended. Example: "best 4k tv india 2026 reviews"

# Phase 2 — Deep Dive (MANDATORY)
For every product found in Phase 1:
1. Call `fetch_product_info` with all ASINs (batched).
2. Call `fetch_reviews` with all ASINs (batched). **Never skip reviews.**
3. For web-only products, use `tavily_search` to find critical/negative reviews.

# Phase 3 — Final Report
Produce a comparison table with these columns at minimum:
| Product | ASIN | Price | Rating (Reviews) | Pros | Cons |

End with a clear verdict and recommendation.

# Rules
- No filler or preamble. Be direct.
- Never use XML tags (`<parameter>`, `<thought>`) inside tool calls.
- Always provide `query` as a plain string and `url_params` as a list of strings.

Current date: {current_date}
Country: India.
"""


def create_product_research_agent(
    model: str = None,
    model_provider: str = None,
    item_limit: int = 5,
    max_researcher_iterations: int = 3,
    target: Literal["amazon", "web"] = None,
    **kwargs # Sink extra args from old signature
):
    """
    Create a single-agent product research assistant.
    """
    if not model:
        raise ValueError("No model specified.")

    llm = _init_llm(model, model_provider)
    now = datetime.now()
    day = now.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    current_date = now.strftime(f"{day}{suffix} %B %Y")

    # All tools are available to the unified agent
    tools = [tavily_search, amazon_direct_search, fetch_product_info, fetch_reviews]
    
    prompt = PRODUCT_RESEARCHER_PROMPT.format(
        current_date=current_date,
        item_limit=item_limit
    )


    # Create the single agent with selected tools
    agent = create_deep_agent(
        model=llm,
        tools=tools,
        system_prompt=prompt,
    )

    limit = (max_researcher_iterations * 10) + 5
    return agent.with_config({"recursion_limit": limit})

def stream_research(
    agent,
    messages: list,
) -> Generator[dict, None, None]:
    """Stream intermediate model responses from the research agent."""
    final_response = ""
    aggregated_usage = {}

    # We want both updates (for tool results/node transitions) and messages (for tokens)
    # Using a list of modes returns tuples of (mode, data)
    for mode, event in agent.stream(
        {"messages": messages},
        stream_mode=["updates", "messages"],
    ):
        if mode == "messages":
            msg, metadata = event
            node_name = metadata.get("langgraph_node", "agent")
            
            # Track token usage if available
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                merge_dicts(aggregated_usage, usage)

            if isinstance(msg, AIMessageChunk):
                # Extract reasoning/thinking from chunks
                reasoning_chunk = ""
                if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
                    reasoning_chunk = msg.additional_kwargs.get("reasoning_content", "")
                
                # Check for reasoning in content list (some models use this)
                content_chunk = ""
                if isinstance(msg.content, str):
                    content_chunk = msg.content
                elif isinstance(msg.content, list):
                    for part in msg.content:
                        if isinstance(part, str):
                            content_chunk += part
                        elif isinstance(part, dict):
                            if part.get("type") == "text":
                                content_chunk += part.get("text", "")
                            elif part.get("type") in ("thought", "reasoning", "thinking"):
                                reasoning_chunk += part.get("text", "") or part.get("thought", "") or ""

                if reasoning_chunk:
                    yield {
                        "type": "thinking_token",
                        "node": node_name,
                        "content": reasoning_chunk,
                    }
                
                if content_chunk:
                    # If this message has tool calls, treat content as thinking/explanation
                    if msg.tool_call_chunks:
                        yield {
                            "type": "thinking_token",
                            "node": node_name,
                            "content": content_chunk,
                        }
                    else:
                        # Otherwise it's part of the final response
                        final_response += content_chunk
                        yield {
                            "type": "token",
                            "node": node_name,
                            "content": content_chunk,
                        }

        elif mode == "updates":
            for node_name, node_output in event.items():
                if not isinstance(node_output, dict):
                    continue

                node_messages = node_output.get("messages", [])
                # Handle langgraph Overwrite objects or other wrappers
                if hasattr(node_messages, "value"):
                    node_messages = node_messages.value
                
                if not isinstance(node_messages, (list, tuple)):
                    node_messages = [node_messages]

                for msg in node_messages:
                    if isinstance(msg, AIMessage):
                        # Extract full reasoning for thinking panel if not already streamed
                        # This serves as a fallback or for non-streaming components
                        if msg.tool_calls:
                            for tool_call in msg.tool_calls:
                                yield {
                                    "type": "tool_call",
                                    "node": node_name,
                                    "tool_name": tool_call.get("name", "unknown"),
                                    "tool_input": tool_call.get("args", {}),
                                    "message": msg,
                                }
                    
                    elif isinstance(msg, ToolMessage):
                        output = msg.content if isinstance(msg.content, str) else str(msg.content)
                        yield {
                            "type": "tool_result",
                            "node": node_name,
                            "tool_name": msg.name if hasattr(msg, "name") else "unknown",
                            "tool_output": output,
                            "message": msg,
                        }

    if final_response:
        yield {
            "type": "final_response",
            "node": "agent",
            "content": final_response,
        }

    # Yield total usage stats if any tokens were recorded
    if aggregated_usage:
        yield {
            "type": "usage",
            "usage": aggregated_usage,
        }
