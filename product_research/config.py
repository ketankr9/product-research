"""Configuration for Product Research Agent."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)


class Config:
    """Configuration container."""
    
    # API Keys
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    
    # Model Configuration
    DEFAULT_GOOGLE_MODEL: str = os.getenv("DEFAULT_GOOGLE_MODEL", "gemini-flash-lite-latest")
    DEFAULT_ANTHROPIC_MODEL: str = os.getenv("DEFAULT_ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    DEFAULT_LOCAL_MODEL: str = os.getenv("DEFAULT_LOCAL_MODEL", "")
    
    # Agent Configuration
    MAX_CONCURRENT_RESEARCH_UNITS: int = 3
    MAX_RESEARCHER_ITERATIONS: int = 3
    
    # Scraper Configuration
    SCRAPER_TIMEOUT: int = 30
    SCRAPER_BACKEND: str = "curl_cffi"  # or "httpx"
    
    # Output Configuration
    OUTPUT_DIR: Path = Path.cwd() / "research_output"
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that required configuration is present."""
        if not cls.TAVILY_API_KEY:
            print("TAVILY_API_KEY is not set. Please set it in the .env file to allow general search.")
        
        if not cls.ANTHROPIC_API_KEY and not cls.GOOGLE_API_KEY:
            # If no API keys are set, we assume local model might be intended, or user will provide keys
            pass
            
        return True
    
    @classmethod
    def get_default_model(cls, provider: str) -> str:
        """Get the default model for a given provider."""
        if provider == "local":
            return cls.DEFAULT_LOCAL_MODEL
        elif provider == "anthropic":
            return cls.DEFAULT_ANTHROPIC_MODEL
        elif provider in ("gemini", "google", "google_genai"):
            return cls.DEFAULT_GOOGLE_MODEL
        else:
            raise ValueError(f"Unknown provider: {provider}")

    @classmethod
    def get_model(cls, provider: str, model: Optional[str] = None) -> str:
        """Get a provider-prefixed model ID string."""
        actual_model = model or cls.get_default_model(provider)
        return f"{provider}:{actual_model}"
    
    @classmethod
    def setup_output_dir(cls) -> Path:
        """Create and return the output directory."""
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        return cls.OUTPUT_DIR

