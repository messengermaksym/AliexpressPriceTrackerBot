import os
import logging
import telebot
from dotenv import load_dotenv
from db_manager import DatabaseManager
from currency_updater import CurrencyUpdater
from aliexpress_parser import AliExpressParser

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize dependencies
db = DatabaseManager()
parser = AliExpressParser()

# Initialize bot for sending notifications
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN) if TOKEN else None

def get_formatted_price(price_usd: float, shipping_usd: float, currency_pref: str, rate: float) -> str:
    total_usd = price_usd + shipping_usd
    total_uah = CurrencyUpdater.convert_usd_to_uah(total_usd, rate)
    
    if currency_pref == "USD":
        return f"${total_usd:.2f} USD"
    elif currency_pref == "UAH":
        return f"{total_uah:.2f} UAH"
    else: # BOTH
        return f"${total_usd:.2f} USD (~{total_uah:.2f} UAH)"

def run_cron():
    if not db.is_ready():
        logger.error("Database client is not initialized. Exiting cron.")
        return
        
    if not bot:
        logger.error("Telegram bot is not initialized. Exiting cron.")
        return

    logger.info("Starting AliExpress price check cron job...")
    
    # Fetch all products that have active subscriptions
    tracked_products = db.get_all_tracked_products()
    logger.info(f"Found {len(tracked_products)} unique product(s) to check.")
    
    if not tracked_products:
        logger.info("No tracked products found. Exiting cron.")
        return

    # Fetch NBU exchange rate
    rate = CurrencyUpdater.get_usd_to_uah_rate()
    
    for product in tracked_products:
        product_id = product["product_id"]
        old_price = float(product["last_price_usd"])
        old_shipping = float(product["last_shipping_usd"] or 0.0)
        old_total = old_price + old_shipping
        
        logger.info(f"Checking product {product_id} (Current saved total: ${old_total:.2f})...")
        
        try:
            # Parse current details
            details = parser.parse_product_details(product_id)
            if not details:
                logger.warning(f"Could not parse details for product {product_id}. Skipping.")
                continue
                
            new_price = details["price_usd"]
            new_shipping = details["shipping_usd"]
            new_total = new_price + new_shipping
            
            logger.info(f"Product {product_id} parsed. New total price: ${new_total:.2f}")
            
            # Check for price drop
            if new_total < old_total:
                savings_usd = old_total - new_total
                savings_uah = CurrencyUpdater.convert_usd_to_uah(savings_usd, rate)
                
                logger.info(f"PRICE DROP DETECTED for product {product_id}! Dropped by ${savings_usd:.2f}")
                
                # Fetch all users subscribed to this product
                subscribers = db.get_product_subscribers(product_id)
                logger.info(f"Notifying {len(subscribers)} subscriber(s) for product {product_id}...")
                
                for sub in subscribers:
                    telegram_id = sub["telegram_id"]
                    currency_pref = sub.get("currency", "BOTH")
                    
                    old_price_text = get_formatted_price(old_price, old_shipping, currency_pref, rate)
                    new_price_text = get_formatted_price(new_price, new_shipping, currency_pref, rate)
                    
                    if currency_pref == "USD":
                        savings_text = f"${savings_usd:.2f} USD"
                    elif currency_pref == "UAH":
                        savings_text = f"{savings_uah:.2f} UAH"
                    else: # BOTH
                        savings_text = f"${savings_usd:.2f} USD (~{savings_uah:.2f} UAH)"
                    
                    notification_text = (
                        f"📉 <b>Зниження ціни!</b>\n\n"
                        f"📌 <b><a href='{details['url']}'>{details['title'][:80]}...</a></b>\n\n"
                        f"🏷️ Стара ціна: <s>{old_price_text}</s>\n"
                        f"🔥 Нова ціна: <b>{new_price_text}</b>\n"
                        f"🎉 Економія: <b>{savings_text}</b>!\n\n"
                        f"🛍️ <a href='{details['url']}'>Купити зараз на AliExpress</a>"
                    )
                    
                    try:
                        # Send notification to user
                        if details["image_url"]:
                            bot.send_photo(telegram_id, details["image_url"], caption=notification_text, parse_mode="HTML")
                        else:
                            bot.send_message(telegram_id, notification_text, parse_mode="HTML", disable_web_page_preview=True)
                        logger.info(f"Notification sent successfully to user {telegram_id} for product {product_id}.")
                    except Exception as e_notify:
                        logger.error(f"Failed to notify user {telegram_id} for product {product_id}: {e_notify}")
                        
            # Upsert product details to update DB state (price, shipping, coupons, coins)
            # This also records the price point in price_history
            db.upsert_product(
                product_id=product_id,
                url=details["url"],
                title=details["title"],
                image_url=details["image_url"],
                price_usd=new_price,
                shipping_usd=new_shipping,
                coin_discount=details["coin_discount"],
                coupons_info=details["coupons_info"]
            )
            logger.info(f"Database updated for product {product_id}.")
            
        except Exception as e:
            logger.error(f"Error checking product {product_id}: {e}")

    logger.info("Cron job finished successfully.")

if __name__ == "__main__":
    run_cron()
