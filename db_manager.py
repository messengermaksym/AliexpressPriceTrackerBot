import os
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            logger.warning("SUPABASE_URL or SUPABASE_KEY not found in environment variables. Database actions will fail.")
            self.client = None
        else:
            try:
                self.client: Client = create_client(url, key)
                logger.info("Supabase client initialized successfully.")
            except Exception as e:
                logger.error(f"Error initializing Supabase client: {e}")
                self.client = None

    def is_ready(self) -> bool:
        return self.client is not None

    # --- User Management ---

    def upsert_user(self, telegram_id: int, username: Optional[str] = None, currency: str = "BOTH") -> bool:
        """
        Creates or updates a user in the database.
        """
        if not self.is_ready():
            return False
        
        user_data = {
            "telegram_id": telegram_id,
            "username": username,
            "currency": currency
        }
        
        try:
            # upsert is supported natively in supabase-py
            self.client.table("users").upsert(user_data).execute()
            logger.info(f"User {telegram_id} upserted successfully.")
            return True
        except Exception as e:
            logger.error(f"Error upserting user {telegram_id}: {e}")
            return False

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetches user preferences by Telegram ID.
        """
        if not self.is_ready():
            return None
        
        try:
            result = self.client.table("users").select("*").eq("telegram_id", telegram_id).execute()
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Error fetching user {telegram_id}: {e}")
            return None

    def update_user_currency(self, telegram_id: int, currency: str) -> bool:
        """
        Updates the preferred currency display for a user ('USD', 'UAH', 'BOTH').
        """
        if not self.is_ready():
            return False
        
        try:
            self.client.table("users").update({"currency": currency}).eq("telegram_id", telegram_id).execute()
            logger.info(f"User {telegram_id} currency updated to {currency}.")
            return True
        except Exception as e:
            logger.error(f"Error updating currency for user {telegram_id}: {e}")
            return False

    # --- Product Management ---

    def upsert_product(self, product_id: str, url: str, title: str, image_url: Optional[str], 
                       price_usd: float, shipping_usd: float = 0.0, coin_discount: float = 0.0, 
                       coupons_info: Optional[str] = None) -> bool:
        """
        Creates or updates a product in the database.
        """
        if not self.is_ready():
            return False
        
        product_data = {
            "product_id": product_id,
            "url": url,
            "title": title,
            "image_url": image_url,
            "last_price_usd": price_usd,
            "last_shipping_usd": shipping_usd,
            "coin_discount": coin_discount,
            "coupons_info": coupons_info,
            "updated_at": "now()" # Update timestamp
        }
        
        try:
            self.client.table("products").upsert(product_data).execute()
            logger.info(f"Product {product_id} upserted successfully.")
            
            # Also record in history
            self.add_price_history(product_id, price_usd, shipping_usd)
            return True
        except Exception as e:
            logger.error(f"Error upserting product {product_id}: {e}")
            return False

    def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves product details by ID.
        """
        if not self.is_ready():
            return None
        
        try:
            result = self.client.table("products").select("*").eq("product_id", product_id).execute()
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Error fetching product {product_id}: {e}")
            return None

    def get_all_tracked_products(self) -> List[Dict[str, Any]]:
        """
        Returns all products that have active subscriptions.
        Used by the scraper cron script.
        """
        if not self.is_ready():
            return []
        
        try:
            # We select products that are referenced in the subscriptions table
            # Supabase/PostgREST does not support distinct directly easily, but we can query all subscriptions 
            # and get unique product_ids or do a join
            result = self.client.table("subscriptions").select("product_id, products(*)").execute()
            products_map = {}
            for item in result.data:
                prod = item.get("products")
                if prod:
                    products_map[prod["product_id"]] = prod
            return list(products_map.values())
        except Exception as e:
            logger.error(f"Error fetching all tracked products: {e}")
            return []

    # --- Subscription Management ---

    def add_subscription(self, telegram_id: int, product_id: str, target_price_usd: Optional[float] = None) -> bool:
        """
        Subscribes a user to a product.
        """
        if not self.is_ready():
            return False
        
        sub_data = {
            "telegram_id": telegram_id,
            "product_id": product_id
        }
        if target_price_usd is not None:
            sub_data["target_price_usd"] = target_price_usd
            
        try:
            self.client.table("subscriptions").upsert(sub_data).execute()
            logger.info(f"User {telegram_id} subscribed to product {product_id}.")
            return True
        except Exception as e:
            logger.error(f"Error subscribing user {telegram_id} to product {product_id}: {e}")
            return False

    def remove_subscription(self, telegram_id: int, product_id: str) -> bool:
        """
        Unsubscribes a user from a product.
        """
        if not self.is_ready():
            return False
        
        try:
            self.client.table("subscriptions").delete().eq("telegram_id", telegram_id).eq("product_id", product_id).execute()
            logger.info(f"User {telegram_id} unsubscribed from product {product_id}.")
            
            # Clean up product if no one else is tracking it (Optional but good practice)
            self._cleanup_orphaned_product(product_id)
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing user {telegram_id} from product {product_id}: {e}")
            return False

    def _cleanup_orphaned_product(self, product_id: str):
        """
        Deletes a product if there are no more active subscriptions.
        """
        try:
            sub_count = self.client.table("subscriptions").select("id", count="exact").eq("product_id", product_id).execute()
            if sub_count.count == 0:
                self.client.table("products").delete().eq("product_id", product_id).execute()
                logger.info(f"Deleted orphaned product {product_id} from database.")
        except Exception as e:
            logger.error(f"Error cleaning up product {product_id}: {e}")

    def get_user_subscriptions(self, telegram_id: int) -> List[Dict[str, Any]]:
        """
        Returns all products a specific user is subscribed to, along with product details.
        """
        if not self.is_ready():
            return []
        
        try:
            result = self.client.table("subscriptions").select("target_price_usd, products(*)").eq("telegram_id", telegram_id).execute()
            subs = []
            for item in result.data:
                product_data = item.get("products")
                if product_data:
                    product_data["target_price_usd"] = item.get("target_price_usd")
                    subs.append(product_data)
            return subs
        except Exception as e:
            logger.error(f"Error fetching subscriptions for user {telegram_id}: {e}")
            return []

    def get_product_subscribers(self, product_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves list of subscriptions (users & target prices) for a given product.
        """
        if not self.is_ready():
            return []
        
        try:
            result = self.client.table("subscriptions").select("target_price_usd, users(*)").eq("product_id", product_id).execute()
            subscribers = []
            for item in result.data:
                user_data = item.get("users")
                if user_data:
                    user_data["target_price_usd"] = item.get("target_price_usd")
                    subscribers.append(user_data)
            return subscribers
        except Exception as e:
            logger.error(f"Error fetching subscribers for product {product_id}: {e}")
            return []

    # --- Price History Management ---

    def add_price_history(self, product_id: str, price_usd: float, shipping_usd: float = 0.0) -> bool:
        """
        Adds a record of a price point to the price history table.
        """
        if not self.is_ready():
            return False
            
        history_data = {
            "product_id": product_id,
            "price_usd": price_usd,
            "shipping_usd": shipping_usd
        }
        
        try:
            self.client.table("price_history").insert(history_data).execute()
            logger.info(f"Price history record added for product {product_id}: ${price_usd} + ${shipping_usd} shipping")
            return True
        except Exception as e:
            logger.error(f"Error adding price history for product {product_id}: {e}")
            return False

    def get_price_history(self, product_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves the price history of a product ordered by recording date.
        """
        if not self.is_ready():
            return []
            
        try:
            result = self.client.table("price_history").select("*").eq("product_id", product_id).order("recorded_at").execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error fetching price history for product {product_id}: {e}")
            return []
