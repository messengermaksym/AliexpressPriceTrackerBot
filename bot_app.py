import os
import logging
import telebot
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv
from db_manager import DatabaseManager
from currency_updater import CurrencyUpdater
from aliexpress_parser import AliExpressParser
from aliexpress_searcher import AliExpressSearcher

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize dependencies
db = DatabaseManager()
parser = AliExpressParser()
searcher = AliExpressSearcher()

# Initialize bot
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN not found in environment variables. Bot will not function.")
    bot = None
else:
    bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# Initialize FastAPI app
app = FastAPI(title="AliExpress Price Tracker Bot")

# Helper function to get currency formatting for a user
def get_user_price_text(price_usd: float, shipping_usd: float, currency_pref: str, rate: float) -> str:
    total_usd = price_usd + shipping_usd
    total_uah = CurrencyUpdater.convert_usd_to_uah(total_usd, rate)
    
    price_uah = CurrencyUpdater.convert_usd_to_uah(price_usd, rate)
    shipping_uah = CurrencyUpdater.convert_usd_to_uah(shipping_usd, rate)
    
    ship_usd_text = f"${shipping_usd:.2f} USD" if shipping_usd > 0 else "Безкоштовно"
    ship_uah_text = f"{shipping_uah:.2f} UAH" if shipping_usd > 0 else "Безкоштовно"
    
    if currency_pref == "USD":
        return (
            f"💵 Ціна: ${price_usd:.2f} USD\n"
            f"🚚 Доставка: {ship_usd_text}\n"
            f"💰 Разом: <b>${total_usd:.2f} USD</b>"
        )
    elif currency_pref == "UAH":
        return (
            f"💵 Ціна: {price_uah:.2f} UAH\n"
            f"🚚 Доставка: {ship_uah_text}\n"
            f"💰 Разом: <b>{total_uah:.2f} UAH</b>"
        )
    else: # BOTH
        return (
            f"💵 Ціна: ${price_usd:.2f} USD (~{price_uah:.2f} UAH)\n"
            f"🚚 Доставка: {ship_usd_text} (~{ship_uah_text})\n"
            f"💰 Разом: <b>${total_usd:.2f} USD (~{total_uah:.2f} UAH)</b>"
        )

# Check if bot is configured
if bot:
    # --- Command Handlers ---

    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        telegram_id = message.from_user.id
        username = message.from_user.username
        
        # Save user to DB
        db.upsert_user(telegram_id, username)
        
        welcome_text = (
            "👋 <b>Привіт! Я бот для відстеження цін на AliExpress.</b>\n\n"
            "Я допоможу тобі купувати товари дешевше. Я буду моніторити ціну на додані товари і надішлю сповіщення, коли ціна впаде.\n\n"
            "🔧 <b>Доступні команди:</b>\n"
            "➕ /add [посилання] — Додати товар до списку відстеження\n"
            "📋 /list — Показати твій список відстежуваних товарів\n"
            "⚙️ /settings — Налаштувати валюту відображення (USD, UAH або обидві)\n"
            "ℹ️ /help — Показати це довідкове повідомлення\n\n"
            "<i>Просто надішли мені посилання на товар з AliExpress (десктопне або мобільне) або скористайся командою /add.</i>"
        )
        bot.reply_to(message, welcome_text)

    @bot.message_handler(commands=['add'])
    def add_product_command(message):
        args = telebot.util.extract_arguments(message.text)
        if not args:
            bot.reply_to(message, "❌ Будь ласка, вкажи посилання після команди. Приклад:\n`/add https://www.aliexpress.com/item/100500...html`", parse_mode="Markdown")
            return
        process_add_url(message, args)

    # Handler for raw URLs sent to the bot directly
    @bot.message_handler(func=lambda message: message.text and ("aliexpress.com" in message.text or "a.aliexpress.com" in message.text))
    def add_product_raw_url(message):
        process_add_url(message, message.text.strip())

    def process_add_url(message, url):
        telegram_id = message.from_user.id
        db.upsert_user(telegram_id, message.from_user.username) # Ensure user exists
        
        # Extract product ID
        product_id = parser.extract_product_id(url)
        if not product_id:
            bot.reply_to(message, "❌ Не вдалося розпізнати посилання. Будь ласка, переконайся, що це правильне посилання на товар AliExpress.")
            return

        status_msg = bot.reply_to(message, "🔍 <i>Зчитуємо інформацію про товар... Це може зайняти кілька секунд.</i>")

        try:
            # Parse product details
            details = parser.parse_product_details(product_id)
            if not details:
                bot.edit_message_text("❌ Не вдалося отримати дані про товар. Можливо, посилання застаріло або AliExpress тимчасово обмежує доступ.", chat_id=message.chat.id, message_id=status_msg.message_id)
                return

            # Upsert product and add subscription
            db.upsert_product(
                product_id=product_id,
                url=details["url"],
                title=details["title"],
                image_url=details["image_url"],
                price_usd=details["price_usd"],
                shipping_usd=details["shipping_usd"],
                coin_discount=details["coin_discount"],
                coupons_info=details["coupons_info"]
            )
            db.add_subscription(telegram_id, product_id, details["price_usd"])

            # Format pricing text
            user_data = db.get_user(telegram_id) or {"currency": "BOTH"}
            currency_pref = user_data.get("currency", "BOTH")
            rate = CurrencyUpdater.get_usd_to_uah_rate()
            price_details_text = get_user_price_text(details["price_usd"], details["shipping_usd"], currency_pref, rate)

            coins_text = f"🪙 Монети: <b>-{details['coin_discount']}%</b>\n" if details["coin_discount"] > 0 else ""
            coupons_text = f"🎟️ Купони: <i>{details['coupons_info']}</i>\n" if details["coupons_info"] else ""

            success_text = (
                f"✅ <b>Товар додано до відстеження!</b>\n\n"
                f"📌 <b><a href='{details['url']}'>{details['title'][:90]}...</a></b>\n\n"
                f"{price_details_text}\n"
                f"{coins_text}"
                f"{coupons_text}\n"
                f"🔎 <i>Шукаємо дешевші альтернативи в інших продавців...</i>"
            )

            # Send result with photo
            bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
            if details["image_url"]:
                sent_msg = bot.send_photo(message.chat.id, details["image_url"], caption=success_text)
            else:
                sent_msg = bot.send_message(message.chat.id, success_text)

            # Search cheaper alternatives asynchronously or in order
            alternatives = searcher.search_cheaper_alternatives(
                original_title=details["title"],
                original_price=details["price_usd"],
                original_shipping=details["shipping_usd"],
                max_results=3
            )

            if alternatives:
                alt_text = "\n💡 <b>Знайдено дешевші альтернативи в інших продавців:</b>\n"
                for idx, alt in enumerate(alternatives):
                    alt_total_usd = alt["price"] + alt["shipping"]
                    alt_total_uah = CurrencyUpdater.convert_usd_to_uah(alt_total_usd, rate)
                    
                    price_display = f"${alt_total_usd:.2f} USD"
                    if currency_pref == "UAH":
                        price_display = f"{alt_total_uah:.2f} UAH"
                    elif currency_pref == "BOTH":
                        price_display = f"${alt_total_usd:.2f} USD (~{alt_total_uah:.2f} UAH)"
                        
                    alt_text += f"\n{idx+1}. <a href='{alt['url']}'>{alt['title'][:50]}...</a>\n   • Вартість з доставкою: <b>{price_display}</b>\n"
                bot.send_message(message.chat.id, alt_text, disable_web_page_preview=True)
            else:
                bot.send_message(message.chat.id, "🔍 <i>Дешевших альтернатив з такою ж назвою наразі не знайдено.</i>")

        except Exception as e:
            logger.error(f"Error processing add product: {e}")
            bot.send_message(message.chat.id, "❌ Сталася помилка при додаванні товару. Спробуйте пізніше.")

    @bot.message_handler(commands=['list'])
    def list_products(message):
        telegram_id = message.from_user.id
        subs = db.get_user_subscriptions(telegram_id)
        
        if not subs:
            bot.reply_to(message, "📋 Твій список відстеження порожній. Надішли мені посилання на товар AliExpress, щоб розпочати.")
            return

        rate = CurrencyUpdater.get_usd_to_uah_rate()
        user_data = db.get_user(telegram_id) or {"currency": "BOTH"}
        currency_pref = user_data.get("currency", "BOTH")

        response = "📋 <b>Товари, які ти відстежуєш:</b>\n"
        
        for idx, sub in enumerate(subs):
            current_total_usd = sub["last_price_usd"] + sub["last_shipping_usd"]
            target_total_usd = sub["target_price_usd"] + sub["last_shipping_usd"] if sub["target_price_usd"] else current_total_usd
            
            diff_usd = current_total_usd - target_total_usd
            
            # Format currency strings
            if currency_pref == "USD":
                price_text = f"${current_total_usd:.2f} USD"
                diff_text = f" (⬇️ -${abs(diff_usd):.2f})" if diff_usd < 0 else (f" (⬆️ +${diff_usd:.2f})" if diff_usd > 0 else "")
            elif currency_pref == "UAH":
                current_total_uah = CurrencyUpdater.convert_usd_to_uah(current_total_usd, rate)
                diff_uah = CurrencyUpdater.convert_usd_to_uah(diff_usd, rate)
                price_text = f"{current_total_uah:.2f} UAH"
                diff_text = f" (⬇️ -{abs(diff_uah):.2f} UAH)" if diff_usd < 0 else (f" (⬆️ +{diff_uah:.2f} UAH)" if diff_usd > 0 else "")
            else: # BOTH
                current_total_uah = CurrencyUpdater.convert_usd_to_uah(current_total_usd, rate)
                price_text = f"${current_total_usd:.2f} USD (~{current_total_uah:.2f} UAH)"
                diff_text = f" (⬇️ знизилась на ${abs(diff_usd):.2f})" if diff_usd < 0 else (f" (⬆️ зросла на ${diff_usd:.2f})" if diff_usd > 0 else "")

            response += (
                f"\n{idx+1}. <b><a href='{sub['url']}'>{sub['title'][:50]}...</a></b>\n"
                f"   • Поточна ціна: <b>{price_text}</b>{diff_text}\n"
                f"   • ID для видалення: <code>/delete {sub['product_id']}</code>\n"
            )
            
        bot.send_message(message.chat.id, response, disable_web_page_preview=True)

    @bot.message_handler(commands=['delete'])
    def delete_product(message):
        args = telebot.util.extract_arguments(message.text)
        if not args:
            bot.reply_to(message, "❌ Будь ласка, вкажи ID товару після команди. Приклад:\n`/delete 1005007171007591`", parse_mode="Markdown")
            return
            
        telegram_id = message.from_user.id
        product_id = args.strip()
        
        product = db.get_product(product_id)
        if not product:
            bot.reply_to(message, "❌ Товар з таким ID не знайдено у списку відстеження.")
            return

        success = db.remove_subscription(telegram_id, product_id)
        if success:
            bot.reply_to(message, f"🗑️ Товар <b>{product['title'][:40]}...</b> видалено зі списку відстеження.")
        else:
            bot.reply_to(message, "❌ Сталася помилка при видаленні товару.")

    @bot.message_handler(commands=['settings'])
    def show_settings(message):
        markup = telebot.types.InlineKeyboardMarkup()
        btn_usd = telebot.types.InlineKeyboardButton("USD 🇺🇸", callback_data="set_curr_USD")
        btn_uah = telebot.types.InlineKeyboardButton("UAH 🇺🇦", callback_data="set_curr_UAH")
        btn_both = telebot.types.InlineKeyboardButton("UAH & USD 🇺🇸🇺🇦", callback_data="set_curr_BOTH")
        markup.row(btn_usd, btn_uah)
        markup.row(btn_both)
        
        telegram_id = message.from_user.id
        user_data = db.get_user(telegram_id) or {"currency": "BOTH"}
        current_currency = user_data.get("currency", "BOTH")
        
        bot.reply_to(
            message,
            f"⚙️ <b>Налаштування валюти відображення</b>\n\n"
            f"Твій поточний режим: <b>{current_currency}</b>\n"
            f"Обери, у якій валюті відображати ціни:",
            reply_markup=markup
        )

    # --- Callback Query Handler ---

    @bot.callback_query_handler(func=lambda call: call.data.startswith("set_curr_"))
    def set_currency_callback(call):
        telegram_id = call.from_user.id
        currency = call.data.replace("set_curr_", "")
        
        db.upsert_user(telegram_id, call.from_user.username)
        db.update_user_currency(telegram_id, currency)
        
        bot.answer_callback_query(call.id, f"Валюту змінено на {currency}!")
        bot.edit_message_text(
            f"⚙️ <b>Налаштування валюти відображення</b>\n\n"
            f"Твій новий режим: <b>{currency}</b> ✅\n"
            f"Змінити знову:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=call.message.reply_markup
        )

# FastAPI routes for Webhook and Healthcheck
@app.get("/")
def read_root():
    return {"status": "online", "message": "AliExpress Price Tracker Bot API is running!"}

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    """
    Receives Telegram update payloads and processes them.
    Used when deploying to Vercel/production.
    """
    if not bot:
        return Response(status_code=500, content="Bot not configured.")
        
    try:
        json_string = await request.json()
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")
        return Response(status_code=400, content=str(e))

@app.get("/api/diagnostics")
def diagnostics():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    sb_url = os.getenv("SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_KEY")
    
    token_status = f"Present (len={len(token)}, ends with {token[-4:]})" if token else "Missing"
    url_status = "Present" if sb_url else "Missing"
    key_status = f"Present (len={len(sb_key)}, starts with {sb_key[:10]}..., ends with ...{sb_key[-10:]})" if sb_key else "Missing"
    
    db_status = "Not initialized"
    db_error = None
    if db.is_ready():
        try:
            res = db.client.table("users").select("*").limit(1).execute()
            db_status = f"Connected successfully (found {len(res.data)} users)"
        except Exception as e:
            db_status = "Error connecting"
            db_error = str(e)
    else:
        db_status = "Client not ready (check URL/Key)"
        
    return {
        "telegram_bot_token": token_status,
        "supabase_url": url_status,
        "supabase_key": key_status,
        "database_status": db_status,
        "database_error": db_error
    }

if __name__ == "__main__":
    # Local execution mode: run bot using Polling (no webhook required)
    if bot:
        logger.info("Starting Telegram Bot in local polling mode...")
        bot.remove_webhook()
        bot.infinity_polling()
    else:
        logger.error("Cannot start bot: Token not configured.")
