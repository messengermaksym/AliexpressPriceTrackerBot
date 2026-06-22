import os
import re
import logging
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class GeminiCleaner:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found in environment variables. Gemini title cleaning is disabled. Using regex fallback.")
            self.model = None
        else:
            try:
                genai.configure(api_key=api_key)
                # Using the fast and cost-effective gemini-2.5-flash model
                self.model = genai.GenerativeModel("gemini-2.5-flash")
                logger.info("Gemini API client initialized successfully.")
            except Exception as e:
                logger.error(f"Error initializing Gemini client: {e}")
                self.model = None

    def clean_title(self, title: str) -> str:
        """
        Cleans a messy AliExpress product title to yield a search-friendly query.
        Uses Gemini if available, otherwise falls back to local regex cleaning.
        """
        if not title:
            return ""

        title = title.strip()

        # If Gemini is configured, use it for intelligent NLP extraction
        if self.model:
            try:
                prompt = (
                    "Analyze the following AliExpress product title and extract a clean, concise search query "
                    "(brand, model name, specific version, e.g., 'Xiaomi Redmi Note 13 Pro 5G' or 'ESP32-WROOM-32D') "
                    "that can be used to search for the exact same or identical product from other sellers. "
                    "Remove all promotional buzzwords (like 'Original', 'Global Version', 'Official Store', 'New', '2025', '2026', 'Sale', 'Promo'), "
                    "spec lists, adjectives, and punctuation. Do NOT include phrases like 'Clean search query:'. "
                    "Output ONLY the final cleaned search string on a single line, with no explanations, no markdown, and no quotes.\n\n"
                    f"AliExpress Title: \"{title}\"\n"
                    "Clean query:"
                )
                logger.info(f"Sending title to Gemini: '{title[:50]}...'")
                response = self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,  # Keep it deterministic
                        max_output_tokens=30
                    )
                )
                cleaned = response.text.strip().replace('"', '').replace("'", "")
                if cleaned:
                    logger.info(f"Gemini Cleaned Title: '{cleaned}'")
                    return cleaned
            except Exception as e:
                logger.error(f"Error during Gemini title cleaning: {e}. Falling back to regex.")

        # Fallback regex cleaner
        return self._regex_fallback_clean(title)

    def _regex_fallback_clean(self, title: str) -> str:
        """
        A local fallback cleaner using regex patterns to remove common spam words.
        """
        # Lowercase for easy parsing
        cleaned = title
        
        # Remove promo words (case insensitive)
        promo_words = [
            r'\boriginal\b', r'\bglobal\b', r'\bversion\b', r'\bofficial\b', r'\bstore\b', 
            r'\bfree\b', r'\bshipping\b', r'\bnew\b', r'\bhot\b', r'\bsale\b', r'\bpromo\b', 
            r'\b202[3456]\b', r'\bbrand\b', r'\bhigh\b', r'\bquality\b', r'\bcheap\b',
            r'\bdiscount\b', r'\bmini\b', r'\bportable\b', r'\bprofessional\b', r'\bupgraded\b'
        ]
        
        for word_pattern in promo_words:
            cleaned = re.sub(word_pattern, '', cleaned, flags=re.IGNORECASE)

        # Replace non-alphanumeric characters with spaces (keep dash, dot, space)
        cleaned = re.sub(r'[^a-zA-Z0-9\.\-\s]', ' ', cleaned)
        
        # Collapse multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        # Grab first 4-5 words (usually contain brand + model)
        words = cleaned.split()
        if len(words) > 4:
            fallback_query = " ".join(words[:4])
        else:
            fallback_query = cleaned

        logger.info(f"Regex Fallback Cleaned Title: '{fallback_query}'")
        return fallback_query

if __name__ == "__main__":
    # Test case
    logging.basicConfig(level=logging.INFO)
    cleaner = GeminiCleaner()
    messy = "Original Global Version Xiaomi Redmi Note 13 Pro 5G SmartPhone Snapdragon 7s Gen 2 200MP Camera 67W Turbo Charge 5100mAh NFC Global Version"
    print(f"Messy: {messy}")
    print(f"Clean: {cleaner.clean_title(messy)}")
