import unittest
from aliexpress_parser import AliExpressParser
from currency_updater import CurrencyUpdater
from gemini_cleaner import GeminiCleaner
from aliexpress_searcher import AliExpressSearcher

class TestAliExpressTracker(unittest.TestCase):
    def setUp(self):
        self.parser = AliExpressParser()
        self.cleaner = GeminiCleaner()
        self.searcher = AliExpressSearcher()

    def test_id_extraction(self):
        """
        Verify product ID extraction from various URL types.
        """
        # Long URLs
        url1 = "https://www.aliexpress.com/item/1005007171007591.html?spm=a2g0o.productlist"
        url2 = "https://m.aliexpress.com/item/1005007171007591.html"
        url3 = "1005007171007591"
        url4 = "https://www.aliexpress.com/item/Original-Xiaomi-14-Pro-1005007171007591.html?sku_id=123"
        
        self.assertEqual(self.parser.extract_product_id(url1), "1005007171007591")
        self.assertEqual(self.parser.extract_product_id(url2), "1005007171007591")
        self.assertEqual(self.parser.extract_product_id(url3), "1005007171007591")
        self.assertEqual(self.parser.extract_product_id(url4), "1005007171007591")
        
        # Invalid URLs
        self.assertIsNone(self.parser.extract_product_id("https://www.google.com"))
        self.assertIsNone(self.parser.extract_product_id(""))

    def test_currency_conversion(self):
        """
        Verify the currency conversion and NBU API fallback wrapper.
        """
        # Check conversion with a fixed rate
        rate = 40.0
        amount_usd = 10.50
        expected_uah = 420.0
        
        converted = CurrencyUpdater.convert_usd_to_uah(amount_usd, rate)
        self.assertEqual(converted, expected_uah)
        
        # Check fallback value
        self.assertGreater(CurrencyUpdater.DEFAULT_RATE, 0.0)

    def test_title_cleaning(self):
        """
        Verify regex fallback title cleaning for promotional keyword removals.
        """
        messy_title = "Original Global Version Xiaomi Redmi Note 13 Pro 5G SmartPhone 2026 New Sale"
        cleaned = self.cleaner._regex_fallback_clean(messy_title)
        
        # Should remove: Original, Global, Version, SmartPhone, 2026, New, Sale
        self.assertNotIn("Original", cleaned)
        self.assertNotIn("Global", cleaned)
        self.assertNotIn("Version", cleaned)
        self.assertNotIn("Sale", cleaned)
        
        # Should keep brand and model
        self.assertIn("Xiaomi", cleaned)
        self.assertIn("Redmi", cleaned)
        self.assertIn("Note", cleaned)

    def test_search_link_filtering(self):
        """
        Verify search engine results URL extraction patterns.
        """
        raw_links = [
            "https://www.aliexpress.com/item/1005007171007591.html",
            "https://r.search.yahoo.com/RU=https%3a%2f%2fwww.aliexpress.com%2fitem%2f1005007171007592.html/RK=2/RS=123"
        ]
        
        # Decode and filter
        import urllib.parse
        decoded = [urllib.parse.unquote(l) for l in raw_links]
        
        # Test extraction via yahoo pattern
        extracted_pids = []
        for l in decoded:
            import re
            match = re.search(r'RU=(https://.*?)(?:/RK=|$)', l)
            if match:
                extracted_pids.append(match.group(1))
            else:
                extracted_pids.append(l)
                
        pids = self.searcher.filter_aliexpress_links(extracted_pids)
        self.assertIn("1005007171007591", pids)
        self.assertIn("1005007171007592", pids)

if __name__ == "__main__":
    unittest.main()
