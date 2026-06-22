import re
import json
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs
from curl_cffi import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AliExpressParser:
    def __init__(self, target_country: str = "UA", target_currency: str = "USD", target_locale: str = "en_US"):
        self.country = target_country
        self.currency = target_currency
        self.locale = target_locale
        # aep_usuc_f cookie specifies region, currency, locale, and site to AliExpress
        self.cookie_val = f"site=glo&c_tp={self.currency}&region={self.country}&b_locale={self.locale}"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,uk;q=0.8,ru;q=0.7",
            "Cookie": f"aep_usuc_f={self.cookie_val};"
        }

    def extract_product_id(self, url_or_id: str) -> Optional[str]:
        """
        Extracts the numeric product ID from a given string/URL.
        Resolves short urls like a.aliexpress.com/xxxxxx first if needed.
        """
        if not url_or_id:
            return None

        # Clean string
        url_or_id = url_or_id.strip()

        # If it's already a numeric product ID
        if url_or_id.isdigit():
            return url_or_id

        # If it is a short link, resolve it
        if "a.aliexpress.com" in url_or_id:
            try:
                logger.info(f"Resolving short URL: {url_or_id}")
                resp = requests.head(url_or_id, headers=self.headers, allow_redirects=True, timeout=10)
                url_or_id = resp.url
                logger.info(f"Resolved to: {url_or_id}")
            except Exception as e:
                logger.error(f"Error resolving short URL: {e}")
                # Fallback to GET request
                try:
                    resp = requests.get(url_or_id, headers=self.headers, allow_redirects=True, timeout=10)
                    url_or_id = resp.url
                    logger.info(f"Resolved (via GET) to: {url_or_id}")
                except Exception as e2:
                    logger.error(f"Error resolving short URL via GET: {e2}")
                    return None

        # Extract ID from long URL
        # Matches: /item/100500123456789.html or /item/some-text-100500123456789.html
        match = re.search(r'/item/.*?(\d+)\.html', url_or_id)
        if match:
            return match.group(1)

        # Match generic number followed by .html
        match = re.search(r'/(\d+)\.html', url_or_id)
        if match:
            return match.group(1)

        return None

    def fetch_page_html(self, product_id: str) -> Optional[str]:
        """
        Fetches the product page HTML using curl_cffi to bypass TLS fingerprinting.
        """
        url = f"https://www.aliexpress.com/item/{product_id}.html"
        logger.info(f"Fetching page: {url}")
        try:
            # We impersonate Chrome 120
            response = requests.get(url, headers=self.headers, impersonate="chrome120", timeout=15)
            if response.status_code == 200:
                return response.text
            else:
                logger.warning(f"Failed to fetch page. Status: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching page html: {e}")
            return None

    def fetch_shipping_cost(self, product_id: str) -> float:
        """
        Calls the internal logistics/freight API of AliExpress to get the shipping cost.
        Returns the shipping cost in USD (0.0 if free, or parsed float).
        """
        url = "https://www.aliexpress.com/aeglodetailweb/api/logistics/freight"
        params = {
            "productId": product_id,
            "count": "1",
            "country": self.country,
            "tradeCurrency": self.currency
        }
        
        headers = self.headers.copy()
        headers["Referer"] = f"https://www.aliexpress.com/item/{product_id}.html"
        headers["Accept"] = "application/json, text/plain, */*"

        try:
            logger.info(f"Fetching shipping cost from logistics API for product {product_id}...")
            resp = requests.get(url, headers=headers, params=params, impersonate="chrome120", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and "body" in data:
                    freight_result = data["body"].get("freightResult", [])
                    if not freight_result:
                        return 0.0 # Free shipping or unavailable

                    # Check for the cheapest/first shipping option
                    first_option = freight_result[0]
                    # Check if free shipping
                    if first_option.get("shippingFee") == "free":
                        return 0.0
                    
                    # Extract amount
                    amount_data = first_option.get("freightAmount", {})
                    amount = amount_data.get("value")
                    if amount is not None:
                        return float(amount)
            else:
                logger.warning(f"Logistics API failed with status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching shipping cost: {e}")
        
        return 0.0

    def parse_product_details(self, product_id: str) -> Optional[Dict[str, Any]]:
        """
        Parses details of a product using its ID.
        Uses Playwright as the primary method, falling back to curl_cffi.
        """
        # Try Playwright first
        try:
            logger.info(f"Attempting to parse product {product_id} with Playwright...")
            result = self._parse_with_playwright(product_id)
            if result and result.get("price_usd") is not None:
                logger.info(f"Successfully parsed product {product_id} with Playwright.")
                return result
        except Exception as e:
            logger.error(f"Playwright parsing failed for product {product_id}: {e}")

        # Fallback to curl_cffi
        logger.info(f"Falling back to curl_cffi for product {product_id}...")
        try:
            return self._parse_with_curl_cffi(product_id)
        except Exception as e:
            logger.error(f"curl_cffi parsing failed for product {product_id}: {e}")
            return None

    def _parse_with_playwright(self, product_id: str) -> Optional[Dict[str, Any]]:
        """
        Uses Playwright headless browser to load the page, trigger client-side scripts, and extract data.
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            
            # Set cookies for destination country & currency
            context.add_cookies([{
                "name": "aep_usuc_f",
                "value": self.cookie_val,
                "domain": ".aliexpress.com",
                "path": "/"
            }])
            
            page = context.new_page()
            url = f"https://www.aliexpress.com/item/{product_id}.html"
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(4000) # Wait 4 seconds for MTOP API calls to complete
            
            title_dom = page.title()
            if "Captcha" in title_dom:
                logger.warning(f"Playwright hit Captcha Interception for item {product_id}")
                browser.close()
                return None
                
            d_c = page.evaluate("() => window._d_c_")
            if not d_c or "lifeCycleEventList" not in d_c:
                logger.warning(f"window._d_c_ not found in Playwright context for item {product_id}")
                browser.close()
                return None
                
            render_data = d_c["lifeCycleEventList"][0].get("data", {})
            
            # 1. Title
            title = None
            global_data = render_data.get("GLOBAL_DATA", {}).get("globalData", {})
            if global_data:
                title = global_data.get("subject")
            if not title:
                title = page.locator('meta[property="og:title"]').get_attribute("content")
            if not title:
                h1s = page.locator("h1").all_text_contents()
                for h in h1s:
                    if h.strip() and h.strip().lower() != "aliexpress":
                        title = h.strip()
                        break
                        
            # 2. Image URL
            image_url = None
            if global_data:
                image_url = global_data.get("imagePath")
            if not image_url and "HEADER_IMAGE_PC" in render_data:
                img_list = render_data["HEADER_IMAGE_PC"].get("imagePathList", [])
                if img_list:
                    image_url = img_list[0]
            if not image_url:
                image_url = page.locator('meta[property="og:image"]').get_attribute("content")
                
            # 3. Price (USD)
            price_usd = None
            price_obj = render_data.get("PRICE", {})
            target_sku_price = price_obj.get("targetSkuPriceInfo", {})
            
            if target_sku_price:
                sale_price_str = target_sku_price.get("salePriceString")
                if sale_price_str:
                    num_match = re.search(r'[\d\.]+', sale_price_str)
                    if num_match:
                        price_usd = float(num_match.group(0))
                
                if price_usd is None:
                    orig_price = target_sku_price.get("originalPrice", {})
                    if orig_price:
                        price_usd = orig_price.get("value")
                        
            if price_usd is None:
                body_text = page.locator("body").inner_text()
                price_matches = re.findall(r'US\s*\$\s*([\d\.]+)', body_text)
                if price_matches:
                    try:
                        price_usd = float(price_matches[0])
                    except ValueError:
                        pass

            # 4. Shipping Cost (USD)
            shipping_usd = 0.0
            shipping_obj = render_data.get("SHIPPING", {})
            layout_info = shipping_obj.get("deliveryLayoutInfo", [])
            if layout_info:
                biz_data = layout_info[0].get("bizData", {})
                if biz_data:
                    disp_amt = biz_data.get("displayAmount")
                    if disp_amt is not None:
                        shipping_usd = float(disp_amt)
                    else:
                        ship_fee = biz_data.get("shippingFee")
                        if ship_fee == "free":
                            shipping_usd = 0.0
                        elif ship_fee:
                            num_match = re.search(r'[\d\.]+', str(ship_fee))
                            if num_match:
                                shipping_usd = float(num_match.group(0))
                                
            # 5. Coins Discount
            coin_discount = 0.0
            page_html = page.content()
            coin_match = re.search(r'(\d+)%\s*(?:off\s*with\s*coins|coins|off\s*using\s*coins)', page_html, re.IGNORECASE)
            if coin_match:
                coin_discount = float(coin_match.group(1))

            # 6. Coupons
            coupons = []
            coupon_block = render_data.get("COUPON_BLOCK_PC", {})
            if coupon_block:
                coupon_list = coupon_block.get("upperCouponBlockViewList", []) or []
                for c in coupon_list:
                    desc = c.get("couponDesc") or c.get("name")
                    if desc:
                        coupons.append(str(desc))
            
            coupon_matches = re.findall(r'US\s*\$\s*(\d+)\s*off\s*on\s*US\s*\$\s*(\d+)', page_html, re.IGNORECASE)
            for off, over in coupon_matches:
                coupons.append(f"US ${off} off over US ${over}")
                
            coupons = list(set(coupons))
            browser.close()
            
            if not title or price_usd is None:
                return None

            return {
                "product_id": product_id,
                "url": url,
                "title": title,
                "image_url": image_url,
                "price_usd": price_usd,
                "shipping_usd": shipping_usd,
                "coin_discount": coin_discount,
                "coupons_info": ", ".join(coupons) if coupons else None
            }

    def _parse_with_curl_cffi(self, product_id: str) -> Optional[Dict[str, Any]]:
        """
        Old curl_cffi raw HTML parsing logic used as fallback.
        """
        html = self.fetch_page_html(product_id)
        if not html:
            logger.warning(f"Could not retrieve HTML fallbacks for product {product_id}")
            return None

        init_data_match = re.search(r'window\.__INIT_DATA__\s*=\s*(\{.*?\});', html)
        run_params_match = re.search(r'window\.runParams\s*=\s*(\{.*?\});', html)
        run_params_script = re.search(r'window\.runParams\s*=\s*(.*?)\s*;\s*window\.', html)

        json_data = None
        try:
            if init_data_match:
                json_data = json.loads(init_data_match.group(1))
            elif run_params_match:
                json_data = json.loads(run_params_match.group(1))
            elif run_params_script:
                json_val = run_params_script.group(1).strip()
                if not json_val.endswith("}"):
                    braces = 0
                    end_idx = 0
                    for idx, char in enumerate(json_val):
                        if char == "{":
                            braces += 1
                        elif char == "}":
                            braces -= 1
                            if braces == 0:
                                end_idx = idx + 1
                                break
                    if end_idx > 0:
                        json_val = json_val[:end_idx]
                json_data = json.loads(json_val)
        except Exception as e:
            logger.error(f"Error parsing fallback JSON: {e}")

        title = None
        image_url = None
        price_usd = None
        coin_discount = 0.0
        coupons = []

        if json_data:
            try:
                data = json_data.get("data", {})
                product_info = data.get("productInfoComponent", {})
                title = product_info.get("subject")
                image_list = product_info.get("productImageList", [])
                if image_list:
                    image_url = image_list[0]
                elif "imagePath" in product_info:
                    image_url = product_info.get("imagePath")

                price_info = data.get("priceComponent", {})
                discount_price = price_info.get("discountPrice", {})
                orig_price = price_info.get("origPrice", {})
                
                price_val = None
                if discount_price:
                    min_amt = discount_price.get("minActivityAmount", {}) or discount_price.get("minAmount", {})
                    if min_amt:
                        price_val = min_amt.get("value")
                
                if price_val is None and orig_price:
                    min_amt = orig_price.get("minAmount", {})
                    if min_amt:
                        price_val = min_amt.get("value")
                
                if price_val is not None:
                    price_usd = float(price_val)
                
                coin_info = price_info.get("coinComponent", {}) or data.get("coinComponent", {})
                if coin_info:
                    coin_discount_text = coin_info.get("coinDiscountText", "")
                    percent_match = re.search(r'(\d+)%', coin_discount_text)
                    if percent_match:
                        coin_discount = float(percent_match.group(1))

                coupon_info = data.get("couponComponent", {}) or data.get("promotionComponent", {})
                if coupon_info:
                    coupon_list = coupon_info.get("couponList", [])
                    for c in coupon_list:
                        desc = c.get("couponDesc") or c.get("name")
                        if desc:
                            coupons.append(str(desc))

            except Exception as e:
                logger.error(f"Error navigating fallback JSON tree: {e}")

        if not title:
            title_match = re.search(r'<h1[^>]*>(.*?)</h1>', html)
            if title_match:
                title = title_match.group(1).strip()
            else:
                meta_title_match = re.search(r'<meta[^>]+property="og:title"[^>]+content="(.*?)"', html)
                if meta_title_match:
                    title = meta_title_match.group(1)

        if not image_url:
            meta_img_match = re.search(r'<meta[^>]+property="og:image"[^>]+content="(.*?)"', html)
            if meta_img_match:
                image_url = meta_img_match.group(1)

        if price_usd is None:
            price_match = re.search(r'\"formatedAmount\":\"\s*US\s*\$\s*([\d\.,]+)\"', html)
            if price_match:
                price_usd = float(price_match.group(1).replace(",", ""))
            else:
                price_json_match = re.search(r'\"price\":\s*\"?([\d\.]+)\"?', html)
                if price_json_match:
                    price_usd = float(price_json_match.group(1))

        shipping_usd = self.fetch_shipping_cost(product_id)

        if not title or price_usd is None:
            return None

        return {
            "product_id": product_id,
            "url": f"https://www.aliexpress.com/item/{product_id}.html",
            "title": title,
            "image_url": image_url,
            "price_usd": price_usd,
            "shipping_usd": shipping_usd,
            "coin_discount": coin_discount,
            "coupons_info": ", ".join(coupons) if coupons else None
        }

if __name__ == "__main__":
    # Quick Local Test cases
    parser = AliExpressParser()
    
    # Test extract id
    test_urls = [
        "https://www.aliexpress.com/item/1005006093859663.html?spm=a2g0o.productlist.main.1",
        "https://m.aliexpress.com/item/1005006093859663.html",
        "1005006093859663"
    ]
    
    logger.info("=== Testing ID Extraction ===")
    for u in test_urls:
        pid = parser.extract_product_id(u)
        logger.info(f"URL: {u} -> Extracted Product ID: {pid}")

    # Test parser with a real item ID (we will use a popular one like a generic ESP32 module or similar if we run it)
    test_id = "1005007171007591" # Change to a known valid ID if needed
    logger.info(f"=== Testing Page Parsing for ID: {test_id} ===")
    details = parser.parse_product_details(test_id)
    logger.info(f"Result: {details}")
