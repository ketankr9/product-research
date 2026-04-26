"""Custom tools for product research."""

import os
import re
from typing import Annotated, Any, Literal, List

from dotenv import load_dotenv
from langchain_core.tools import InjectedToolArg, StructuredTool, tool

from .scraper import WebScraper, html_to_markdown, MarkdownConverter, clean_markdown

# Default converter choice, can be overridden
DEFAULT_MARKDOWN_CONVERTER = MarkdownConverter.HTML2TEXT

# Load environment variables from .env file and bash environment
load_dotenv()

# Tavily client initialized lazily
_tavily_client = None


def _get_tavily_client():
    """Get or create Tavily client (lazy initialization)."""
    global _tavily_client
    if _tavily_client is None:
        TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
        if not TAVILY_API_KEY:
            return None
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
    return _tavily_client


# --- Tavily Search Tool ---
def tavily_search_sync(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
) -> str:
    """Synchronous web search for Tavily."""
    scraper = WebScraper()
    tavily_client = _get_tavily_client()
    if not tavily_client:
        return "Search failed: TAVILY_API_KEY not set. Web search is disabled."

    try:
        search_results = tavily_client.search(
            query=query,
            max_results=max_results,
            topic=topic,
            include_answer="advanced",
            include_favicon=False,
            include_images=False,
            # include_raw_content='markdown', ## Disabled for now.
            # chunks_per_source=1,
            # exclude_domains=["youtube.com", "youtu.be"]
        )
    except Exception as e:
        return f"Search failed: {e}"

    # print(search_results)
    
    results = []
    if search_results.get("answer"):
        results.append({"type": "answer", "content": search_results['answer']})
    
    for result in search_results.get("results", []):
        results.append({
            "type": "result",
            "title": result.get("title", "Untitled"),
            "url": result.get("url", ""),
            "content": result.get("content", "")
        })
    
    import json
    return json.dumps(results, indent=2)



tavily_search = StructuredTool.from_function(
    func=tavily_search_sync,
    name="tavily_search",
    description="Search the web using Tavily and fetch full webpage content as markdown."
)


# --- Amazon Direct Search Tool ---
def amazon_direct_search_sync(
    query: str,
    url_params: List[str] = None,
    max_results: int = 10,
) -> str:
    """Sync Amazon search."""
    import urllib.parse
    from bs4 import BeautifulSoup

    # Validate url_params
    if url_params:
        for p in url_params:
            if not isinstance(p, str) or not p.startswith('&'):
                raise ValueError(f"Malformed url_param: '{p}'. Each parameter must be a string starting with '&'.")

    scraper = WebScraper()
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.amazon.in/s?k={encoded_query}"
    
    if url_params:
        url += "".join(url_params)
    try:
        html_content = scraper.fetch(url, timeout=20)
    except Exception as e:
        return f"Amazon search failed: {e}"
    soup = BeautifulSoup(html_content, "html.parser")
    products = []

    def _is_sponsored(item) -> bool:
        """Return True if this search result item is a sponsored/ad listing."""
        if item.get('data-component-type') == 'sp-sponsored-result':
            return True
        if item.select_one('.s-sponsored-label-info-icon, .AdHolder'):
            return True
        for span in item.select('span'):
            if span.get_text(strip=True).lower() == 'sponsored':
                return True
        return False
    
    # Improved parsing logic
    # Look for search result items specifically
    for item in soup.select('div[data-component-type="s-search-result"]'):
        asin = item.get('data-asin')
        if not asin or len(asin) != 10: continue
        
        # Skip sponsored / ad listings
        if _is_sponsored(item): continue
        
        # Avoid duplicates
        if any(p['asin'] == asin for p in products): continue
        
        # Robust title extraction
        title_elem = (item.select_one('h2 a span') or 
                      item.select_one('span.a-size-medium.a-text-normal') or
                      item.select_one('span.a-size-base-plus.a-text-normal') or 
                      item.select_one('span.a-text-normal') or
                      item.select_one('h2 span'))
        
        if not title_elem: continue
        title = title_elem.get_text(strip=True)
        if not title: continue
        
        # Price extraction
        price_elem = item.select_one('.a-price-whole')
        price = price_elem.get_text(strip=True) if price_elem else "N/A"
        
        # Rating extraction
        rating_elem = item.select_one('i.a-icon-star-small .a-icon-alt, i.a-icon-star .a-icon-alt, .a-icon-alt, [aria-label*="out of 5 stars"]')
        rating_val = "N/A"
        if rating_elem:
            rating_text = rating_elem.get_text(strip=True) or rating_elem.get('aria-label', "")
            match = re.search(r'(\d+\.?\d*)', rating_text)
            if match:
                rating_val = match.group(1)
        
        # Review count
        reviews_elem = item.select_one('span[aria-label*="ratings"], span[aria-label*="reviews"], span.a-size-base.s-underline-text, span.a-size-mini.s-underline-text')
        reviews_count = ""
        if reviews_elem:
            reviews_text = reviews_elem.get('aria-label', "") or reviews_elem.get_text(strip=True)
            # Extract the count part, e.g., "37 ratings" -> "37", "(1,234)" -> "1,234"
            reviews_count = reviews_text.strip('()').split()[0]
        
        rating = rating_val

        products.append({
            'asin': asin, 
            'title': title, 
            'price': price,
            'rating': rating,
            'reviews': reviews_count,
            'url': f"https://www.amazon.in/dp/{asin}"
        })
        if len(products) >= max_results: break
        
    if not products: 
        # Fallback to any [data-asin] if specific result items not found (also filters sponsored)
        for item in soup.select('[data-asin]'):
            asin = item.get('data-asin')
            if not asin or len(asin) != 10: continue
            if _is_sponsored(item): continue
            if any(p['asin'] == asin for p in products): continue
            title_elem = item.select_one('h2, .a-text-normal')
            if not title_elem: continue
            title = title_elem.get_text(strip=True)
            if not title: continue

            # Basic price/rating for fallback as well
            price_elem = item.select_one('.a-price-whole')
            price = price_elem.get_text(strip=True) if price_elem else "N/A"
            
            rating_elem = item.select_one('i.a-icon-star-small .a-icon-alt, i.a-icon-star .a-icon-alt, .a-icon-alt, [aria-label*="out of 5 stars"]')
            rating_val = "N/A"
            if rating_elem:
                rating_text = rating_elem.get_text(strip=True) or rating_elem.get('aria-label', "")
                match = re.search(r'(\d+\.?\d*)', rating_text)
                if match:
                    rating_val = match.group(1)
            
            reviews_elem = item.select_one('span[aria-label*="ratings"], span[aria-label*="reviews"], span.a-size-base.s-underline-text, span.a-size-mini.s-underline-text')
            reviews_count = ""
            if reviews_elem:
                reviews_text = reviews_elem.get('aria-label', "") or reviews_elem.get_text(strip=True)
                reviews_count = reviews_text.strip('()').split()[0]
            
            rating = rating_val

            products.append({
                'asin': asin, 
                'title': title, 
                'price': price,
                'rating': rating,
                'reviews': reviews_count,
                'url': f"https://www.amazon.in/dp/{asin}"
            })
            if len(products) >= max_results: break

    if not products: return f"No products found or failed to parse Amazon.in for '{query}'."
    
    import json
    return json.dumps(products, indent=2)



amazon_direct_search = StructuredTool.from_function(
    func=amazon_direct_search_sync,
    name="amazon_direct_search",
    description="Search for products directly on Amazon.in. Returns up to 10 most relevant ASINs and titles."
)


# --- Product Info Fetcher Tool ---

def _clean_amazon_html(soup):
    """Clean Amazon-specific HTML fragment by removing unwanted elements."""
    if not soup:
        return ""
    
    # Unwrap most tags to keep text but lose attributes/structure
    for tag in ['a', 'i', 'span', 'div', 'p', 'b', 'strong', 'em']:
        if soup.name == tag:
            continue
        for element in soup.find_all(tag):
            element.unwrap()
        
    return str(soup)


def _clean_markdown_text(text: str) -> str:
    """Remove redundant Amazon-specific phrases from markdown."""
    # Remove "About this item" header (handles various markdown formats)
    text = re.sub(r'(?i)^\s*[*_#]*\s*About this item\s*[*_#]*\s*$', '', text, flags=re.MULTILINE)
    # Remove "See more product details" link/text
    text = re.sub(r'(?i).*See more product details.*', '', text)
    # Remove "Extracted Exact Price" label if it exists (since CLI shows it separately)
    text = re.sub(r'(?i)\*\*Extracted Exact Price:\*\*.*', '', text)
    # Remove excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def fetch_product_info_batch(asins: List[str]) -> str:
    """Fetch product information (specs, price, dimensions) for multiple Amazon products in batch.
    
    Args:
        asins: List of 10-character Amazon ASINs (max 10 items will be processed).
    """
    asins = asins[:10]
    scraper = WebScraper()
    results = []
    
    # We use a helper to process single ASIN
    def _get_info(asin):
        match = re.search(r'\b[B0][A-Z0-9]{9}\b', asin)
        target_asin = match.group(0) if match else asin
        url = f"https://www.amazon.in/dp/{target_asin}"
        try:
            html_content = scraper.fetch(url, timeout=30)
            
            # Extract specific sections
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Extract exact price using specified id and class
            price_div = soup.find(id="corePriceDisplay_desktop_feature_div")
            extracted_price = "Not found"
            if price_div:
                price_elem = price_div.find(class_="a-price-whole")
                if price_elem:
                    extracted_price = price_elem.text.strip()
            
            # Extract product title
            title_tag = soup.find(id="productTitle")
            product_title = title_tag.get_text(strip=True) if title_tag else "Unknown Product"
            # Truncate title if too long for display (cli will handle it but cleaner here)
            if len(product_title) > 150:
                product_title = product_title[:147] + "..."
            
            # Extract specific sections
            product_details_div = soup.find(id="feature-bullets")
            # reviews_div = soup.find(id="reviewsMedley")
            
            # Clean sections
            center_col_md = html_to_markdown(_clean_amazon_html(product_details_div), converter=DEFAULT_MARKDOWN_CONVERTER) if product_details_div else "Product details section not found."
            center_col_md = _clean_markdown_text(center_col_md)
            
            content = center_col_md

            if len(content) > 25000:
                print(f"Content for ASIN: {target_asin} is too long at {len(center_col_md)} of center_col_md and {len(reviews_md)} or reviews characters. Truncating to 25000 characters.")
                
            # Ensure price doesn't have double currency symbol if already present
            price_str = str(extracted_price).strip()
            if price_str != "Not found" and not price_str.startswith("₹"):
                price_str = f"₹{price_str}"
                
            return {
                "asin": target_asin,
                "title": product_title,
                "price": price_str,
                "details": content[:25000]
            }
        except Exception as e:
            return {
                "asin": target_asin,
                "error": str(e)
            }

    for asin in asins:
        results.append(_get_info(asin))
        
    import json
    return json.dumps(results, indent=2)


fetch_product_info = StructuredTool.from_function(
    func=fetch_product_info_batch,
    name="fetch_product_info",
    description="Fetch product information (specs, price, dimensions) for a list of Amazon ASINs in batch."
)


# --- Critical Review Reader Tool ---

from .amazon_review_scraper import AmazonReviewScraper

def fetch_reviews_batch(asins: List[str]) -> str:
    """Fetch critical (one-star) reviews for multiple Amazon products in batch.
    
    Args:
        asins: List of 10-character Amazon ASINs (max 10 items will be processed).
    """
    asins = asins[:10]
    scraper = AmazonReviewScraper()
    results = []
    
    def _get_reviews(asin):
        match = re.search(r'\b[B0][A-Z0-9]{9}\b', asin)
        target_asin = match.group(0) if match else asin
        
        try:
            # Try getting reviews from the direct reviews link first
            # This API requires sign-in, which is not supported, hence commented out.
            reviews_data = None # scraper.scrape_from_reviews_page(target_asin)
            
            # If that failed (likely due to login wall), try the product page as heartbeat/fallback
            if not reviews_data:
                # print(f"Direct reviews URL failed for {target_asin}, falling back to reviws in product page.")
                reviews_data = scraper.scrape_from_product_page(target_asin)
            
            if not reviews_data or not reviews_data.get("reviews"):
                return f"### Reviews for ASIN: {target_asin}\nNo reviews found (likely blocked by sign-in wall).\n"
            
            product_title = reviews_data.get("title") or "Unknown Product"
            if len(product_title) > 150:
                product_title = product_title[:147] + "..."
            reviews_text = reviews_data.get("reviews")
            
            return {
                "asin": target_asin,
                "title": product_title,
                "reviews": reviews_text
            }
        except Exception as e:
            return {
                "asin": target_asin,
                "error": str(e)
            }

    for asin in asins:
        results.append(_get_reviews(asin))
        
    import json
    return json.dumps(results, indent=2)


fetch_reviews = StructuredTool.from_function(
    func=fetch_reviews_batch,
    name="fetch_reviews",
    description="Fetch critical (one-star) reviews for a list of Amazon ASINs in batch to identify flaws."
)
