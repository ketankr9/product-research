"""Web scraping module with support for curl_cffi and httpx."""

import time
from enum import Enum
from typing import Optional

from curl_cffi import requests as curl_requests


class ScraperBackend(Enum):
    """Available scraper backends."""
    CURL_CFFI = "curl_cffi"
    HTTPX = "httpx"


class MarkdownConverter(Enum):
    """Available markdown converters."""
    MARKDOWNIFY = "markdownify"
    HTML2TEXT = "html2text"


class WebScraper:
    """
    Web scraper with bot detection evasion.
    
    Supports multiple backends:
    - curl_cffi: Best for bypassing bot detection (uses real browser TLS fingerprint)
    - httpx: Fast async HTTP client for simpler sites
    """
    
    def __init__(self, backend: ScraperBackend = ScraperBackend.CURL_CFFI):
        self.backend = backend
        self._session = None
        
    def _get_headers(self) -> dict:
        """Get realistic browser headers to avoid bot detection."""
        return {
            "Referer": "https://www.amazon.in/",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            "device-memory": "8",
            "downlink": "10",
            "dpr": "2",
            "ect": "4g",
            "rtt": "0",
            "sec-ch-device-memory": "8",
            "sec-ch-dpr": "2",
            "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
            "sec-ch-ua-full-version-list": '"Chromium";v="146.0.7680.165", "Not-A.Brand";v="24.0.0.0", "Google Chrome";v="146.0.7680.165"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-ch-ua-platform-version": '"26.3.1"',
            "sec-ch-viewport-width": "770",
            "viewport-width": "770",
        }
    
    def fetch(self, url: str, timeout: int = 30, max_retries: int = 3) -> str:
        """
        Fetch content from URL using the configured backend with retries.
        
        Args:
            url: URL to fetch
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries
            
        Returns:
            HTML content as string
        """
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                if self.backend == ScraperBackend.CURL_CFFI:
                    return self._fetch_curl_cffi(url, timeout)
                else:
                    return self._fetch_httpx(url, timeout)
            except RuntimeError as e:
                last_error = e
                if attempt < max_retries:
                    # Exponential backoff: 2s, 4s, 8s
                    wait_time = 2 ** (attempt + 1)
                    # print(f"Fetch failed, retrying in {wait_time}s ({attempt + 1}/{max_retries}): {e}")
                    time.sleep(wait_time)
                    continue
        raise last_error
    
    def _fetch_curl_cffi(self, url: str, timeout: int) -> str:
        """Fetch using curl_cffi with browser impersonation."""
        try:
            response = curl_requests.get(
                url,
                headers=self._get_headers(),
                timeout=timeout,
                impersonate="safari15_3",  # Impersonate Safari browser which seems to work better for Amazon.in
                allow_redirects=True,
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            raise RuntimeError(f"Failed to fetch {url} with curl_cffi: {e}")
    
    
    def _fetch_httpx(self, url: str, timeout: int) -> str:
        """Fetch using httpx."""
        import httpx
        
        try:
            with httpx.Client(headers=self._get_headers(), follow_redirects=True) as client:
                response = client.get(url, timeout=timeout)
                response.raise_for_status()
                return response.text
        except Exception as e:
            raise RuntimeError(f"Failed to fetch {url} with httpx: {e}")



def clean_markdown(markdown: str) -> str:
    """
    Clean up excessive whitespace, remove images, and simplify links to plain text.
    """
    import re
    
    # Remove image references: ![alt](url)
    markdown = re.sub(r'!\[.*?\]\(.*?\)', '', markdown)
    
    # Convert links to plain text: [text](url) -> text
    markdown = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', markdown)
    
    # Clean up excessive whitespace (3 or more newlines to 2)
    markdown = re.sub(r'\n\s*\n\s*\n+', '\n\n', markdown)
    
    # Clean up trailing spaces from each line
    markdown = re.sub(r'[ \t]+$', '', markdown, flags=re.MULTILINE)
    
    return markdown.strip()


def html_to_markdown(html: str, converter: MarkdownConverter = MarkdownConverter.MARKDOWNIFY) -> str:
    """
    Convert HTML content to markdown.
    
    Args:
        html: HTML content
        converter: Converter to use (markdownify or html2text)
        
    Returns:
        Markdown formatted text
    """
    from bs4 import BeautifulSoup
    
    # Pre-parse with BeautifulSoup to strip unwanted elements
    soup = BeautifulSoup(html, "html.parser")
    
    # Elements to decompose (completely remove)
    unwanted_selectors = [
        "script", "style", "nav", "header", "footer", "aside",
        "img", "svg", "video", "canvas", "input", "button", "iframe",
        "[aria-hidden='true']",
        # Amazon specific or generic UI elements
        ".a-button", ".cr-image-carousel", ".a-spinner-wrapper",
        ".review-image-tile-section", ".cr-lightbox-view-image-gallery",
        ".review-with-images-section", ".a-declarative"
    ]
    
    for selector in unwanted_selectors:
        for element in soup.select(selector):
            element.decompose()
            
    # Get cleaned HTML
    cleaned_html = str(soup)
    
    if converter == MarkdownConverter.MARKDOWNIFY:
        from markdownify import markdownify as md
        # Custom configuration for better markdown output
        markdown = md(
            cleaned_html,
            heading_style="ATX",
            bullets="-",
            escape_asterisks=True,
            escape_underscores=True,
        )
    else:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        h.ignore_emphasis = False
        h.body_width = 0  # No wrapping
        h.ignore_mailto_links = True
        markdown = h.handle(cleaned_html)
    
    return clean_markdown(markdown)
