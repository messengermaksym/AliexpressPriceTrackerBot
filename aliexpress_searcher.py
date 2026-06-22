import re
import urllib.parse
import logging
from typing import List, Dict, Any
from curl_cffi import requests
from bs4 import BeautifulSoup
from gemini_cleaner import GeminiCleaner
from aliexpress_parser import AliExpressParser

logger = logging.getLogger(__name__)

class AliExpressSearcher:
    def __init__(self, target_country: str = "UA", target_currency: str = "USD", target_locale: str = "en_US"):
        self.country = target_country
        self.currency = target_currency
        self.locale = target_locale
        self.cleaner = GeminiCleaner()
        self.parser = AliExpressParser(target_country, target_currency, target_locale)

    def search_cheaper_alternatives(self, original_title: str, original_price: float, original_shipping: float = 0.0, max_results: int = 3) -> List[Dict[str, Any]]:
        """
        Cleans the product title, searches AliExpress product pages via Yahoo/DDG,
        parses the details of the top search results using Playwright,
        compares prices (including shipping), and returns cheaper alternatives.
        """
        cleaned_query = self.cleaner.clean_title(original_title)
        if not cleaned_query:
            logger.warning("Empty search query after cleaning. Cannot search.")
            return []

        logger.info(f"Searching for cheaper alternatives for query: '{cleaned_query}'...")
        product_ids = self.search_aliexpress_products(cleaned_query)
        if not product_ids:
            logger.info("No product IDs found in search.")
            return []

        original_total = original_price + original_shipping
        logger.info(f"Target total price: ${original_total:.2f} (Price: ${original_price:.2f} + Shipping: ${original_shipping:.2f})")

        alternatives = []
        # Limit to checking first 5 found product IDs to conserve resources and avoid timeouts
        for pid in product_ids[:5]:
            try:
                logger.info(f"Parsing potential alternative product ID: {pid}...")
                details = self.parser.parse_product_details(pid)
                if not details:
                    continue
                
                price = details.get("price_usd")
                shipping = details.get("shipping_usd", 0.0)
                if price is None:
                    continue
                    
                total_price = price + shipping
                
                # Verify similarity to prevent matching unrelated cheap accessories
                title_lower = details.get("title", "").lower()
                query_words = cleaned_query.lower().split()
                # Must contain at least 50% of the keywords (or at least 2 if query has multiple words)
                match_count = sum(1 for w in query_words if w in title_lower)
                match_threshold = max(2, len(query_words) // 2) if len(query_words) > 1 else 1
                
                if match_count >= match_threshold:
                    details["total_price"] = total_price
                    # Check if it is actually cheaper
                    if total_price < original_total:
                        alternatives.append(details)
                        logger.info(f"FOUND CHEAPER ALTERNATIVE: {details['title'][:40]}... Total: ${total_price:.2f}")
                    else:
                        logger.info(f"Not cheaper: {details['title'][:40]}... Total: ${total_price:.2f}")
                else:
                    logger.info(f"Skipping (not similar): {details['title'][:40]}...")
            except Exception as e:
                logger.error(f"Error parsing alternative {pid}: {e}")

        # Sort by total price ascending
        alternatives.sort(key=lambda x: x["total_price"])
        return alternatives[:max_results]

    def search_aliexpress_products(self, query: str) -> List[str]:
        """
        Finds AliExpress product IDs by searching on Yahoo and DuckDuckGo.
        """
        # Try Yahoo first as it is very reliable and has high limits
        pids = self.search_yahoo(query)
        if pids:
            return pids
        # Fallback to DuckDuckGo
        pids = self.search_ddg(query)
        return pids

    def search_yahoo(self, query: str) -> List[str]:
        """
        Queries Yahoo Search for indexed AliExpress product pages.
        """
        search_query = f"site:aliexpress.com/item/ {query}"
        url = f"https://search.yahoo.com/search?p={urllib.parse.quote(search_query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        logger.info(f"Querying Yahoo Search: {url}")
        try:
            resp = requests.get(url, headers=headers, impersonate="chrome120", timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    # Yahoo redirect links are often inside RU=...
                    decoded_href = urllib.parse.unquote(href)
                    if "aliexpress.com/item/" in decoded_href:
                        match = re.search(r'RU=(https://.*?)(?:/RK=|$)', decoded_href)
                        if match:
                            links.append(match.group(1))
                        else:
                            links.append(decoded_href)
                            
                return self.filter_aliexpress_links(links)
            logger.warning(f"Yahoo Search failed with status: {resp.status_code}")
        except Exception as e:
            logger.error(f"Yahoo Search error: {e}")
        return []

    def search_ddg(self, query: str) -> List[str]:
        """
        Queries DuckDuckGo HTML Search for indexed AliExpress product pages.
        """
        search_query = f"site:aliexpress.com/item/ {query}"
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(search_query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        logger.info(f"Querying DuckDuckGo Search: {url}")
        try:
            resp = requests.get(url, headers=headers, impersonate="chrome120", timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = []
                for a in soup.find_all("a", href=True):
                    href = urllib.parse.unquote(a["href"])
                    if "aliexpress.com/item/" in href:
                        if "uddg=" in href:
                            extracted = href.split("uddg=")[1].split("&")[0]
                            links.append(extracted)
                        else:
                            links.append(href)
                return self.filter_aliexpress_links(links)
            logger.warning(f"DDG Search failed with status: {resp.status_code}")
        except Exception as e:
            logger.error(f"DDG Search error: {e}")
        return []

    def filter_aliexpress_links(self, links: List[str]) -> List[str]:
        """
        Extracts product IDs from list of links and returns unique list.
        """
        pids = []
        for l in links:
            match = re.search(r'/item/.*?(\d+)\.html', l)
            if match:
                pid = match.group(1)
                pids.append(pid)
        return list(set(pids))

if __name__ == "__main__":
    # Test Searcher
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    searcher = AliExpressSearcher()
    
    # We simulate a search for a cheaper alternative to a flying ball (original price $5.00)
    results = searcher.search_cheaper_alternatives(
        original_title="Flying ball, automatic spinning ball, LED dazzling lights, floating magic",
        original_price=5.00,
        original_shipping=1.50,
        max_results=2
    )
    
    print("\n=== Search Results ===")
    for idx, r in enumerate(results):
        print(f"[{idx+1}] {r['title']}")
        print(f"    URL: {r['url']}")
        print(f"    Price: ${r['price_usd']} + ${r['shipping_usd']} shipping = Total: ${r['total_price']}")
