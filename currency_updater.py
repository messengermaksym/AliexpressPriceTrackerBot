import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CurrencyUpdater:
    NBU_API_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=USD&json"
    DEFAULT_RATE = 41.0  # Safe fallback rate if API fails

    @classmethod
    def get_usd_to_uah_rate(cls) -> float:
        """
        Fetches the official USD to UAH exchange rate from the National Bank of Ukraine API.
        If the API is down, returns a fallback rate.
        """
        try:
            logger.info("Fetching USD to UAH rate from NBU API...")
            response = requests.get(cls.NBU_API_URL, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    rate = data[0].get("rate")
                    if rate:
                        logger.info(f"NBU Exchange Rate fetched: 1 USD = {rate} UAH")
                        return float(rate)
            logger.warning(f"Failed to fetch exchange rate from NBU (Status: {response.status_code}). Using fallback: {cls.DEFAULT_RATE}")
        except Exception as e:
            logger.error(f"Error fetching USD exchange rate from NBU: {e}. Using fallback: {cls.DEFAULT_RATE}")
        
        return cls.DEFAULT_RATE

    @classmethod
    def convert_usd_to_uah(cls, amount_usd: float, rate: Optional[float] = None) -> float:
        """
        Converts USD to UAH. If rate is not provided, fetches it automatically.
        """
        if rate is None:
            rate = cls.get_usd_to_uah_rate()
        return round(amount_usd * rate, 2)

if __name__ == "__main__":
    # Quick Test
    logging.basicConfig(level=logging.INFO)
    rate = CurrencyUpdater.get_usd_to_uah_rate()
    logger.info(f"Test conversion of $10.50: {CurrencyUpdater.convert_usd_to_uah(10.50, rate)} UAH")
