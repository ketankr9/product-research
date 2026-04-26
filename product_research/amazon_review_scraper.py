import sys
import os
import time
from typing import List, Dict
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

# Add current directory to path
sys.path.append(os.getcwd())

class AmazonReviewScraper:
    def __init__(self, impersonate="safari15_3"):
        self.impersonate = impersonate
        self.session = curl_requests.Session(impersonate=impersonate)
        self.headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-language": "en-GB,en;q=0.9",
            "cache-control": "max-age=0",
            "device-memory": "8",
            "downlink": "10",
            "dpr": "2",
            "ect": "4g",
            "priority": "u=0, i",
            "rtt": "50",
            "sec-ch-device-memory": "8",
            "sec-ch-dpr": "2",
            "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-ch-ua-platform-version": '"15.4.1"',
            "sec-ch-viewport-width": "1728",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        }

    def scrape_from_product_page(self, asin: str) -> dict:
        """Scrapes reviews from the main product page (avoids login wall)."""
        url = f"https://www.amazon.in/dp/{asin}"
        
        headers = self.headers.copy()
        headers["referer"] = "https://www.google.com/"
        
        response = self.session.get(url, headers=headers, impersonate=self.impersonate)
        if response.status_code != 200:
            print(f"Error: Status {response.status_code}")
            return {"title": "", "reviews": ""}
            
        html = response.text
        if "Amazon Sign-In" in html:
            print("Blocked by Login wall.")
            return {"title": "", "reviews": ""}
            
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract product title
        title_tag = soup.find(id="productTitle")
        product_title = title_tag.get_text(strip=True) if title_tag else ""

        review_text = ""

        ai_summary = soup.find("div", {"data-testid":"overall-summary"})
        if ai_summary:
            ai_summary = ai_summary.get_text(strip=True)
            review_text += f"### Amazon AI Summary\n{ai_summary}\n\n"
        
        # Amazon's review selectors on the product page
        review_elements = soup.select("#cm-cr-dp-review-list .review, .review")
        if not review_elements:
             # Fallback to data-hook
             review_elements = soup.find_all("div", {"data-hook": "review"})
             
        for element in review_elements:
            # Extract basic info
            title_node = element.find("a", {"class": "review-title-content"})
            if not title_node:
                title_node = element.find("a", {"data-hook": "review-title"})
            
            if title_node:
                # Remove star rating icon from title text if nested
                for star in title_node.find_all("i", {"data-hook": "review-star-rating"}):
                    star.decompose()
                title = title_node.get_text(strip=True)
            else:
                title = "No Title"
            
            body_node = element.find("div", {"class": "review-text-content"})
            body = body_node.get_text(strip=True) if body_node else "No Body"
            
            review_text += f"***\n**{title}**\n{body}\n"
            
        return {"title": product_title, "reviews": review_text}

    def scrape_from_reviews_page(self, asin: str) -> str:
        """Attempt to scrape from the reviews URL."""
        url = f"https://www.amazon.in/product-reviews/{asin}/ref=cm_cr_dp_d_show_all_btm?ie=UTF8"
        print(f"Fetching reviews from direct link: {url}")

        headers = self.headers.copy()
        headers["referer"] = f"https://www.amazon.in/dp/{asin}"
        headers["sec-fetch-site"] = "same-origin"

        response = self.session.get(url, headers=headers, impersonate=self.impersonate, allow_redirects=True)
        print(f"Response status: {response.status_code}")
        html = response.text
        
        if "Amazon Sign-In" in html:
            print("Status: Blocked by Login Wall.")
            # print(html[:500])
            return ""
            
        if response.status_code != 200:
            print(f"Failed to fetch reviews page. Status: {response.status_code}")
            return ""
            
        soup = BeautifulSoup(html, "html.parser")
        review_elements = soup.find_all("div", {"data-hook": "review"})
        
        review_text = ""
        for element in review_elements:
            rating_node = element.find("i", {"data-hook": "review-star-rating"}) or element.find("i", class_="a-icon-star")
            rating = rating_node.get_text(strip=True) if rating_node else "No Rating"

            title_node = element.find("a", {"data-hook": "review-title"}) or element.find("span", {"data-hook": "review-title"})
            if title_node:
                # Remove star rating icon from title text if nested
                for star in title_node.find_all("i", {"data-hook": "review-star-rating"}):
                    star.decompose()
                title = title_node.get_text(strip=True)
            else:
                title = "No Title"
            
            body_node = element.find("span", {"data-hook": "review-body"})
            body = body_node.get_text(strip=True) if body_node else "No Body"
            
            review_text += f"***\n**{title}** ({rating})\n{body}\n"
            
        return review_text

if __name__ == "__main__":
    scraper = AmazonReviewScraper()
    asin = "B0FM8189JM"
        
    print("\n" + "-" * 30)
    print("Method 2: Product Page (Establish Session)")
    print("-" * 30)
    reviews = scraper.scrape_from_product_page(asin)
    print(reviews)

    print("-" * 30)
    print("Method 1: Direct Reviews URL")
    print("-" * 30)
    reviews = scraper.scrape_from_reviews_page(asin)
    if reviews:
        print(reviews)
    else:
        print("Failed to get reviews from direct URL.")
