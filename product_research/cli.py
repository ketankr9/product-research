"""CLI interface for General Product Research Agent (Amazon & Web)."""

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import click
from dotenv import load_dotenv
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status
from rich.table import Table
from rich.columns import Columns
from rich.traceback import install

from .agents import create_product_research_agent, stream_research
from .scraper import MarkdownConverter
from . import tools
from langchain_core.messages import AIMessage, HumanMessage

# Load environment variables from .env file and bash environment
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Install rich traceback for better error messages
install(show_locals=True)

console = Console()

# Regex to match http/https URLs
_URL_RE = re.compile(r"(https?://[^\s\)\]\'\"\,]+)")


def linkify(text: str) -> str:
    """Wrap any URLs in *text* with Rich's clickable link markup.

    Terminals that support OSC 8 (iTerm2, Kitty, modern Terminal.app, etc.)
    will render these as actual clickable hyperlinks.
    """
    return _URL_RE.sub(r"[link=\1]\1[/link]", text)


# Regex to find Amazon product page URLs (captures ASIN)
_AMZN_URL_RE = re.compile(
    r"(https?://(?:www\.)?amazon\.in/(?:[^/\s]+/)?dp/([A-Z0-9]{10})[^\s\)\]\'\",]*)"
)
# Regex to capture the nearest label before a URL (e.g. bold/heading text)
_LABEL_RE = re.compile(
    r"(?:\*{1,2}([^*\n]{3,80})\*{1,2}|#{1,4}\s+([^\n]{3,80}))\s*\n?.*?(https?://[^\s]+)"
)


def print_product_links(response: str, is_amazon: bool = True) -> None:
    """Extract product URLs from *response* and print them as a clickable panel."""
    # Collect (url, label) pairs in order, deduplicated
    seen_urls: dict[str, str] = {}  # url -> label
    
    if is_amazon:
        # Collect (url, asin) pairs in order, deduplicated
        seen_asins: dict[str, str] = {}  # asin -> url
        for m in _AMZN_URL_RE.finditer(response):
            url, asin = m.group(1), m.group(2)
            if asin not in seen_asins:
                seen_asins[asin] = url

        if not seen_asins:
            return

        # Try to find a label (bold text / heading) near each URL in the raw text
        # Build a quick map of asin -> candidate label from context
        asin_labels: dict[str, str] = {}
        lines = response.splitlines()
        for i, line in enumerate(lines):
            m = _AMZN_URL_RE.search(line)
            if not m:
                continue
            asin = m.group(2)
            if asin in asin_labels:
                continue
            # Walk backwards up to 5 lines to find the nearest non-empty heading/bold
            for j in range(i, max(i - 6, -1), -1):
                candidate = lines[j].strip()
                # Strip markdown bold/italic/heading markers
                clean = re.sub(r"[#*_|]+", "", candidate).strip()
                # Accept if it looks like a product name (>5 chars, not just a URL)
                if len(clean) > 5 and not clean.startswith("http") and not clean.startswith("|"):
                    asin_labels[asin] = clean[:60]
                    break
        
        for asin, url in seen_asins.items():
            seen_urls[url] = asin_labels.get(asin, asin)
    else:
        # General web search link extraction
        for m in _URL_RE.finditer(response):
            url = m.group(1)
            if url not in seen_urls:
                # Try to find label for this URL
                label = url
                lines = response.splitlines()
                for i, line in enumerate(lines):
                    if url in line:
                        for j in range(i, max(i - 6, -1), -1):
                            candidate = lines[j].strip()
                            clean = re.sub(r"[#*_|]+", "", candidate).strip()
                            if len(clean) > 5 and not clean.startswith("http") and not clean.startswith("|"):
                                label = clean[:60]
                                break
                        break
                seen_urls[url] = label

    if not seen_urls:
        return

    lines_out = []
    for idx, (url, label) in enumerate(seen_urls.items(), 1):
        lines_out.append(f"  {idx}. [bold]{label}[/bold]")
        lines_out.append(f"     [link={url}]{url}[/link]")

    body = "\n".join(lines_out)
    console.print()
    console.print(
        Panel(
            body,
            title="[bold cyan]🛒 Product Links[/bold cyan]",
            border_style="cyan",
            padding=(0, 1),
        )
    )


def _resolve_model_config(
    model: Optional[str] = None,
    model_provider: Optional[str] = None
) -> tuple[str, str]:
    """Determine the model and provider to use."""
    from .config import Config
    
    # Provider-prefixed model (e.g. "anthropic:claude-3-sonnet") takes precedence
    if model and ":" in model:
        provider, model_name = model.split(":", 1)
        return model_name, provider

    # Decide provider
    actual_provider = model_provider
    if not actual_provider:
        # Fallback to available API keys
        if os.getenv("ANTHROPIC_API_KEY"):
            actual_provider = "anthropic"
        elif os.getenv("GOOGLE_API_KEY"):
            actual_provider = "google"
        else:
            # Default fallback
            actual_provider = "google"


    if actual_provider == "google":
        actual_provider = "google_genai"
        
    actual_model = model or Config.get_default_model(actual_provider)
    return actual_model, actual_provider


from rich.live import Live

class ResearchSession:
    """Manages a research session with conversation history."""
    
    def __init__(self, agent, output_dir: Optional[Path] = None, target: str = "amazon"):
        self.agent = agent
        self.output_dir = output_dir or Path.cwd()
        self.messages = []
        self.research_count = 0
        self.target = target
        self.asin_to_title = {}
        
    def run_research(self, query: str, show_intermediate: bool = True) -> tuple[str, dict]:
        """Run a research query and return (result, usage).
        
        Args:
            query: The research query to run.
            show_intermediate: If True, print intermediate model responses.
        """
        self.research_count += 1
        
        # Add user message to history
        self.messages.append(HumanMessage(content=query))
        
        response = ""
        display_response = ""
        usage = {}
        
        if show_intermediate:
            # Stream with intermediate output
            live_response = None
            current_thinking = ""
            thinking_panel = None
            assistant_timestamp = None
            
            for event in stream_research(self.agent, self.messages):
                event_type = event["type"]
                node = event.get("node", "")
                
                # Stop live response if a different event type comes in
                if event_type != "token" and live_response:
                    live_response.stop()
                    live_response = None
                    display_response = ""
                    assistant_timestamp = None
                
                if event_type == "thinking_token":
                    content = event["content"]
                    current_thinking += content
                    
                    if not thinking_panel:
                        thinking_panel = Live(
                            Panel(Markdown(current_thinking), title=f"[bold cyan]💭 Thinking...[/bold cyan]", border_style="cyan", style="dim cyan"),
                            console=console,
                            refresh_per_second=10,
                        )
                        thinking_panel.start()
                    else:
                        thinking_panel.update(Panel(Markdown(current_thinking), title=f"[bold cyan]💭 Thinking...[/bold cyan]", border_style="cyan", style="dim cyan"))
                
                elif event_type != "thinking_token" and thinking_panel:
                    thinking_panel.stop()
                    thinking_panel = None
                
                elif event_type == "thinking":
                    # Fallback for old thinking events if any
                    content = event["content"]
                    console.print(Panel(
                        linkify(content),
                        title=f"[bold cyan]💭 {node} Thinking[/bold cyan]",
                        border_style="cyan",
                        padding=(0, 1),
                        style="dim cyan"
                    ))
                    
                elif event_type == "token":
                    content = event["content"]
                    response += content
                    display_response += content
                    
                    if not assistant_timestamp:
                        assistant_timestamp = datetime.now().strftime("%H:%M")
                    
                    assistant_title = f"[bold green]Assistant ({assistant_timestamp})[/bold green]"
                    
                    if not live_response:
                        live_response = Live(
                            Panel(Markdown(display_response), title=assistant_title, border_style="green"),
                            console=console,
                            refresh_per_second=10,
                        )
                        live_response.start()
                    else:
                        live_response.update(Panel(Markdown(display_response), title=assistant_title, border_style="green"))

                elif event_type == "tool_call":
                    tool_name = event["tool_name"]
                    tool_input = str(event.get("tool_input", {}))
                    # Trim long tool inputs
                    if len(tool_input) > 200:
                        tool_input = tool_input[:200] + "..."
                    
                    console.print(f"\n  [bold yellow]🛠️  Calling {tool_name}...[/bold yellow]")
                    if tool_input and tool_input != "{}":
                        console.print(f"    [dim]Input: {linkify(tool_input)}[/dim]")
                    
                elif event_type == "tool_result":
                    tool_name = event.get("tool_name", "")
                    output = event.get("tool_output", "")
                    self._display_tool_result(tool_name, output)

                elif event_type == "final_response":
                    # Use the accumulated response if tokens were streamed, otherwise use this
                    if not response:
                        response = event["content"]
                
                elif event_type == "usage":
                    usage = event
            
            if live_response:
                live_response.stop()
                live_response = None
        else:
            # Non-streaming fallback
            result = self.agent.invoke({"messages": self.messages})
            
            if hasattr(result, "get") and "messages" in result:
                last_msg = result["messages"][-1]
                if isinstance(last_msg, AIMessage):
                    # Extract usage if present in the final message
                    u = getattr(last_msg, "usage_metadata", None)
                    if u:
                        usage = u
                    elif "usage" in last_msg.additional_kwargs:
                        usage = last_msg.additional_kwargs["usage"]
            
            if hasattr(result, "get"):
                if "messages" in result:
                    messages = result["messages"]
                    for msg in reversed(messages):
                        if hasattr(msg, "content") and msg.content:
                            response = msg.content
                            break
                    if not response:
                        response = str(messages[-1]) if messages else str(result)
                elif "output" in result:
                    response = result["output"]
                else:
                    response = str(result)
            else:
                response = str(result)
        
        # Add assistant response to history
        if response:
            self.messages.append(AIMessage(content=response))
        
        # Save the research result
        self._save_result(query, response)
        
        return response, usage
    
    def _display_tool_result(self, tool_name: str, output: Any) -> None:
        """Display tool results beautifully based on the tool type."""
        import json
        
        # Header for the tool result
        console.print(f"\n  [bold green]✓ {tool_name}[/bold green]")
        
        if tool_name == "amazon_direct_search":
            try:
                products = json.loads(output)
                if isinstance(products, list):
                    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 1))
                    table.add_column("#", justify="right", style="dim")
                    table.add_column("Product Title", style="cyan", width=60)
                    table.add_column("Price", style="green")
                    table.add_column("Rating", style="yellow")
                    
                    for idx, p in enumerate(products, 1):
                        asin = p.get('asin')
                        title = p.get('title', 'Unknown')
                        if len(title) > 70:
                            title = title[:67] + "..."
                        
                        if asin:
                            self.asin_to_title[asin] = title

                        price = f"₹{p.get('price', 'N/A')}" if p.get('price') != 'N/A' else "N/A"
                        rating_val = p.get('rating', 'N/A')
                        reviews_count = p.get('reviews', '')
                        rating = f"{rating_val} ({reviews_count})" if reviews_count else rating_val
                        if "out of 5 stars" in rating:
                            rating = rating.split(" ")[0] + "⭐"
                        elif rating_val != 'N/A':
                            # Add a star if it's a numeric rating
                            rating = rating.replace(rating_val, f"{rating_val}⭐")
                        
                        table.add_row(
                            str(idx),
                            linkify(title),
                            price,
                            rating
                        )
                    
                    console.print(Panel(table, title="Search Results", border_style="green", padding=(0, 1)))
                    return
            except Exception:
                pass # Fallback to default rendering

        elif tool_name == "tavily_search":
            try:
                results = json.loads(output)
                if isinstance(results, list):
                    for item in results:
                        if item.get("type") == "answer":
                            console.print(Panel(item.get("content", ""), title="Tavily Quick Answer", border_style="cyan"))
                        else:
                            title = item.get("title", "Untitled")
                            url = item.get("url", "")
                            content = item.get("content", "")
                            console.print(f"  [bold cyan]• {linkify(title)}[/bold cyan]")
                            console.print(f"    [dim]{linkify(url)}[/dim]")
                            if content:
                                # Truncate snippet
                                snippet = content[:200] + "..." if len(content) > 200 else content
                                console.print(f"    [italic]{snippet}[/italic]\n")
                    return
            except Exception:
                pass
        
        elif tool_name == "fetch_product_info":
             # Product info is often long markdown, but we can make it nicer
             content = str(output)
             if "### Product Info for" in content:
                 sections = content.split("===PRODUCT_SECTION===")
                 for section in sections:
                     if not section.strip(): continue
                     # Try parsing new standardized format
                     title_match = re.search(r"### PRODUCT_INFO: (.*?) \(([A-Z0-9]{10})\)", section)
                     if title_match:
                         product_title = title_match.group(1)
                         asin = title_match.group(2)
                     else:
                         # Fallback
                         asin_match = re.search(r"([A-Z0-9]{10})", section)
                         asin = asin_match.group(1) if asin_match else "Unknown"
                         product_title = self.asin_to_title.get(asin, "")

                     display_name = f"{product_title} ({asin})" if product_title else asin
                     
                     price_match = re.search(r"PRICE: (₹[\d,]+|Not found)", section)
                     price = price_match.group(1) if price_match else ""
                     
                     # Extract details section
                     details = section.split("DETAILS:")[1] if "DETAILS:" in section else section
                     
                     renderables = []
                     if price:
                         renderables.append(f"[bold green]{price}[/bold green]")
                     renderables.append(Markdown(details.strip()))
                     
                     # Ensure display name is not too long for the title
                     if len(display_name) > 80:
                         display_name = display_name[:77] + "..."
                     
                     console.print(Panel(
                         Group(*renderables), 
                         title=f"📦 {display_name}", 
                         border_style="blue",
                         padding=(0, 1),
                         expand=False
                     ))
                 return

        elif tool_name == "fetch_reviews":
            content = str(output)
            if "### PRODUCT_REVIEWS" in content:
                sections = content.split("===PRODUCT_SECTION===")
                for section in sections:
                    if not section.strip(): continue
                    
                    # Try parsing new standardized format
                    title_match = re.search(r"### PRODUCT_REVIEWS: (.*?) \(([A-Z0-9]{10})\)", section)
                    if title_match:
                        product_title = title_match.group(1)
                        asin = title_match.group(2)
                    else:
                        # Fallback
                        asin_match = re.search(r"([A-Z0-9]{10})", section)
                        asin = asin_match.group(1) if asin_match else "Unknown"
                        product_title = self.asin_to_title.get(asin, "")

                    display_name = f"{product_title} ({asin})" if product_title else asin
                    
                    # Extract content after REVIEWS:
                    raw_reviews = section.split("REVIEWS:")[1] if "REVIEWS:" in section else section

                    # Distinguish AI Summary vs User Reviews
                    final_content = ""
                    if "### Amazon AI Summary" in raw_reviews:
                        parts = raw_reviews.split("### Amazon AI Summary")
                        # parts[1] starts with the AI summary content, then --- then user reviews
                        ai_parts = parts[1].split("---", 1)
                        ai_summary = ai_parts[0].strip()
                        
                        final_content += f"### 🤖 Amazon AI Summary\n{ai_summary}\n\n-----\n"
                        
                        if len(ai_parts) > 1:
                            user_reviews = ai_parts[1].strip()
                            if user_reviews:
                                final_content += f"### 👤 User Critical Reviews\n{user_reviews}"
                    else:
                        final_content = raw_reviews

                    # Ensure display name is not too long for the title
                    if len(display_name) > 80:
                        display_name = display_name[:77] + "..."

                    console.print(Panel(
                        Markdown(final_content),
                        title=f"⭐ {display_name}",
                        border_style="yellow",
                        padding=(0, 1),
                        expand=False
                    ))
                return

        # Default rendering for other tools or fallback
        preview = str(output).strip()
        lines = preview.split("\n")
        if len(lines) > 20:
            preview = "\n".join(lines[:20]) + "\n\n[dim]... content truncated for display ...[/dim]"
        elif len(preview) > 3000:
            preview = preview[:3000] + "..."
            
        indented_preview = "\n".join(f"    {line}" for line in preview.split("\n"))
        console.print(linkify(indented_preview))
        console.print()

    def _save_result(self, query: str, response: str):
        """Save research result to file."""
        filename = f"research_{self.research_count:03d}.md"
        filepath = self.output_dir / filename
        
        target_name = "Amazon" if self.target == "amazon" else "Web"
        content = f"""# {target_name} Product Research #{self.research_count}

## Query
{query}

## Results
{response}
"""
        filepath.write_text(content)
        console.print(f"[dim]Saved to [link=file://{filepath.resolve()}]{filepath}[/link][/dim]")


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """General Product Research Agent
    
    A deep research agent powered by LangChain that helps you find
    the best products on Amazon or the general web through 
    comprehensive research and analysis.
    
    Examples:
    
    \b
        # Start interactive session
        research-agent chat
        
        # Run single research query
        research-agent research "best hand steamer under 2000"
        
        # Web search instead of Amazon
        research-agent research "best mesh wifi system 2024" --target web
        
    """
    pass


@cli.command()
@click.argument("query", required=False)
@click.option("--output", "-o", type=click.Path(file_okay=False), default=None,
              help="Output directory for research results")
@click.option("--model", "-m", default=None,
              help="High-end model (planner) to use")
@click.option("--model-provider", type=click.Choice(["local", "anthropic", "google"]), default=None,
              help="Model providers to choose from. Auto-detected if not set.")
@click.option("--low-end-model", "-lm", default=None,
              help="Low-end model (worker) to use")
@click.option("--target", "-t", type=click.Choice(["amazon", "web"]), default=None,
              help="Search target (amazon.in or general web)")
@click.option("--max-iterations", "-i", default=5, type=int,
              help="Maximum research iterations")
@click.option("--items", "-n", default=5, type=int,
              help="Number of products to research")
@click.option("--converter", type=click.Choice(["markdownify", "html2text"]), default="markdownify",
              help="HTML to Markdown converter")
def research(query: Optional[str], output: Optional[str], model: Optional[str], model_provider: Optional[str], low_end_model: Optional[str], target: str, max_iterations: int, items: int, converter: str):
    """Run a product research query.
    
    If QUERY is provided, run a single research task.
    If QUERY is omitted, enters interactive mode.
    """
    # Validate API keys
    if not os.getenv("TAVILY_API_KEY"):
        console.print("[red]Error:[/red] TAVILY_API_KEY environment variable is required")
        sys.exit(1)
    
    # Resolve models
    resolved_model, resolved_provider = _resolve_model_config(model, model_provider)

    # Provider-specific key checks after resolution
    if resolved_provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY is required for 'anthropic' provider")
        sys.exit(1)
    elif resolved_provider in ("gemini", "google") and not os.getenv("GOOGLE_API_KEY"):
        console.print("[red]Error:[/red] GOOGLE_API_KEY is required for Gemini provider")
        sys.exit(1)

    output_dir = Path(output) if output else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[dim]Initializing agent with target={target}, provider={resolved_provider}, model={resolved_model}...[/dim]")
    # Set converter
    if converter == "html2text":
        tools.DEFAULT_MARKDOWN_CONVERTER = MarkdownConverter.HTML2TEXT
    else:
        tools.DEFAULT_MARKDOWN_CONVERTER = MarkdownConverter.MARKDOWNIFY


    if low_end_model:
        console.print(f"[dim]Using low-end model={low_end_model}[/dim]")

    try:
        from .agents import create_product_research_agent
        agent = create_product_research_agent(
            model=resolved_model,
            model_provider=resolved_provider,
            low_end_model=low_end_model,
            item_limit=items,
            max_researcher_iterations=max_iterations,
            target=target,
        )
    except Exception as e:
        console.print(f"[red]Failed to initialize agent: {e}[/red]")
        sys.exit(1)
    
    session = ResearchSession(agent, output_dir, target=target)
    
    if query:
        # Single query mode
        target_name = "Amazon" if target == "amazon" else "Web"
        console.print(Panel(f"[bold blue]Researching:[/bold blue] {query}", title=f"{target_name} Product Research"))
        console.print()
        
        try:
            result, usage = session.run_research(query)
            print_product_links(result, is_amazon=(target == "amazon"))
            
            if usage:
                console.print("\n[dim]Model Usage Stats:[/dim]")
                raw_usage = usage.get("usage", usage)
                console.print(raw_usage)
        except Exception as e:
            console.print(f"[red]Research failed: {e}[/red]")
            console.print_exception()
            sys.exit(1)
    else:
        # Interactive mode
        target_name = "Amazon" if target == "amazon" else "Web"
        console.print(Panel(f"[bold green]Interactive Research Mode ({target_name})[/bold green]\n"
                        "Type your research queries. Type 'quit' or 'exit' to end.",
                        title="Product Research Agent"))
        console.print()
        
        while True:
            try:
                user_query = Prompt.ask("[bold blue]Research[/bold blue]")
                
                if user_query.lower() in ["quit", "exit", "q"]:
                    console.print("[dim]Goodbye![/dim]")
                    break
                
                if not user_query.strip():
                    continue
                
                result, usage = session.run_research(user_query)
                print_product_links(result, is_amazon=(target == "amazon"))
                
                if usage:
                    console.print("\n[dim]Model Usage Stats:[/dim]")
                    raw_usage = usage.get("usage", usage)
                    console.print(raw_usage)
                console.print()
                console.print("-" * 60)
                console.print()
                
            except KeyboardInterrupt:
                console.print("\n[dim]Interrupted. Type 'quit' to exit.[/dim]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                console.print_exception()


@cli.command()
@click.option("--model", "-m", default=None, help="High-end model (planner)")
@click.option("--model-provider", type=click.Choice(["local", "anthropic", "google"]), default=None,
              help="Model providers to choose from. Auto-detected if not set.")
@click.option("--low-end-model", "-lm", default=None, help="Low-end model (worker)")
@click.option("--target", "-t", type=click.Choice(["amazon", "web"]), default="amazon",
              help="Search target (amazon.in or general web)")
@click.option("--items", "-n", default=10, type=int,
              help="Number of products to research")
@click.option("--converter", type=click.Choice(["markdownify", "html2text"]), default="markdownify",
              help="HTML to Markdown converter")
def chat(model: Optional[str] = None, model_provider: Optional[str] = None, low_end_model: Optional[str] = None, target: str = "amazon", items: int = 5, converter: str = "markdownify"):
    """Start an interactive chat session with follow-up support.
    
    This mode maintains conversation context, allowing you to ask
    follow-up questions about previous research.
    """
    # Validate API keys
    if not os.getenv("TAVILY_API_KEY"):
        console.print("[red]Error:[/red] TAVILY_API_KEY environment variable is required")
        sys.exit(1)
    
    # Resolve models
    resolved_model, resolved_provider = _resolve_model_config(model, model_provider)

    # Provider-specific key checks after resolution
    if resolved_provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY is required for 'anthropic' provider")
        sys.exit(1)
    elif resolved_provider in ("google_genai", "gemini") and not os.getenv("GOOGLE_API_KEY"):
        console.print("[red]Error:[/red] GOOGLE_API_KEY is required for Gemini provider")
        sys.exit(1)
    
    target_name = "Amazon" if target == "amazon" else "Web"
    target_desc = "Amazon.in" if target == "amazon" else "the general web"
    
    console.print(Panel.fit(
        f"[bold green]{target_name} Product Research Chat[/bold green]\n\n"
        f"Ask about products on {target_desc}. You can ask follow-up questions!\n\n"
        "[dim]Commands:[/dim]\n"
        "  [yellow]/clear[/yellow]   - Clear conversation history\n"
        "  [yellow]/save[/yellow]   - Save conversation to file\n"
        "  [yellow]/quit[/yellow]   - Exit the chat",
        title="Welcome"
    ))
    console.print()

    console.print(f"[dim]Initializing agent with target={target}, provider={resolved_provider}, model={resolved_model}...[/dim]")
    # Set converter
    if converter == "html2text":
        tools.DEFAULT_MARKDOWN_CONVERTER = MarkdownConverter.HTML2TEXT
    else:
        tools.DEFAULT_MARKDOWN_CONVERTER = MarkdownConverter.MARKDOWNIFY


    if low_end_model:
        console.print(f"[dim]Using low-end model={low_end_model}[/dim]")

    # Create the agent
    try:
        from .agents import create_product_research_agent
        agent = create_product_research_agent(
            model=resolved_model,
            model_provider=resolved_provider,
            low_end_model=low_end_model,
            item_limit=items,
            target=target,
        )
    except Exception as e:
        console.print(f"[red]Failed to initialize agent: {e}[/red]")
        sys.exit(1)
    
    session = ResearchSession(agent, target=target)
    
    while True:
        try:
            user_input = Prompt.ask("[bold blue]You[/bold blue]")
            
            if user_input.lower() in ["quit", "exit", "q", "/quit", "/exit", "/q"]:
                console.print("[dim]Goodbye! Happy shopping![/dim]")
                break
            
            if user_input.lower() == "/clear":
                session.messages = []
                console.print("[dim]Conversation history cleared.[/dim]")
                continue
            
            if user_input.lower() == "/save":
                filename = f"chat_session_{session.research_count:03d}.md"
                content = "# Chat Session\n\n"
                for msg in session.messages:
                    role = "User" if isinstance(msg, HumanMessage) else "Assistant"
                    content += f"## {role}\n{msg.content}\n\n"
                Path(filename).write_text(content)
                console.print(f"[dim]Saved to {filename}[/dim]")
                continue
            
            if not user_input.strip():
                continue
            
            result, usage = session.run_research(user_input)
            
            if usage:
                console.print("\n[dim]Model Usage Stats:[/dim]")
                raw_usage = usage.get("usage", usage)
                console.print(raw_usage)
            console.print()
            
        except KeyboardInterrupt:
            console.print("\n[dim]Type '/quit' to exit.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            console.print_exception()


@cli.command()
def check():
    """Check if all required environment variables are set."""
    console.print("[bold]Environment Check[/bold]\n")

    tavily_key = os.getenv("TAVILY_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    google_key = os.getenv("GOOGLE_API_KEY")

    # Check Tavily (always required)
    if tavily_key:
        masked = tavily_key[:4] + "..." + tavily_key[-4:] if len(tavily_key) > 8 else "****"
        console.print(f"[green]✓[/green] TAVILY_API_KEY: {masked} (Required for web search)")
        tavily_ok = True
    else:
        console.print(f"[red]✗[/red] TAVILY_API_KEY: Not set (Required for web search)")
        tavily_ok = False

    # Check LLM provider
    llm_any_ok = False
    if anthropic_key:
        masked = anthropic_key[:4] + "..." + anthropic_key[-4:] if len(anthropic_key) > 8 else "****"
        console.print(f"[green]✓[/green] ANTHROPIC_API_KEY: {masked} (Claude models)")
        llm_any_ok = True
    else:
        console.print(f"[dim]○[/dim] ANTHROPIC_API_KEY: Not set (Claude models)")

    if google_key:
        masked = google_key[:4] + "..." + google_key[-4:] if len(google_key) > 8 else "****"
        console.print(f"[green]✓[/green] GOOGLE_API_KEY: {masked} (Gemini models)")
        llm_any_ok = True
    else:
        console.print(f"[dim]○[/dim] GOOGLE_API_KEY: Not set (Gemini models)")

    # Check for local is now just descriptive
    console.print(f"[dim]○[/dim] Local Models: Available via --model-provider google")

    console.print()
    if tavily_ok and llm_any_ok:
        console.print("[green]✓ Key environment variables are set![/green]")
        console.print("\n[dim]You can now run:[/dim]")
        console.print("  ./run.sh chat")
        console.print("  ./run.sh research 'hand steamer'")
    else:
        console.print("[yellow]! Some environment variables are missing.[/yellow]")
        console.print("\n[dim]Set them in your shell or .env file if needed:[/dim]")
        console.print("  export TAVILY_API_KEY=your_key_here")
        console.print("  export GOOGLE_API_KEY=your_key_here")


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
