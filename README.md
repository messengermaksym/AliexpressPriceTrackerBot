# AliExpress Price Tracker Telegram Bot

Telegram-бот для відстеження цін на товари з AliExpress з автоматичним сповіщенням про зниження ціни, аналізом купонів/монет та розумним пошуком дешевших альтернатив в інших продавців (з урахуванням доставки).

Проект розроблений для **100% безкоштовного хостингу** з використанням безкоштовного тарифного плану Vercel, Supabase та GitHub Actions.

---

## 🛠️ Архітектура проекту
1. **База даних:** Supabase (хмарна PostgreSQL, безкоштовно).
2. **Telegram Bot:** FastAPI (Python), розгорнутий на Vercel Serverless (безкоштовно, працює 24/7).
3. **Оновлення цін (Cron):** GitHub Actions (безкоштовно). Парсить актуальні ціни через Playwright кожні 6 годин, порівнює їх з історією та надсилає сповіщення.
4. **Розумний пошук:** Gemini 1.5 Flash API (безкоштовно) для очищення назв товарів та Yahoo Search для знаходження альтернатив.

---

## 🚀 Кроки для налаштування

### Крок 1. Налаштування бази даних Supabase
1. Зареєструйтеся на [Supabase](https://supabase.com/) та створіть новий безкоштовний проект.
2. Перейдіть до розділу **SQL Editor** та запустіть наступний запит для створення таблиць:

```sql
-- Таблиця користувачів
CREATE TABLE users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    currency VARCHAR(10) DEFAULT 'BOTH', -- 'USD', 'UAH', 'BOTH'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Таблиця товарів
CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    image_url TEXT,
    last_price_usd NUMERIC(10, 2) NOT NULL,
    last_shipping_usd NUMERIC(10, 2) DEFAULT 0.00,
    coin_discount NUMERIC(5, 2) DEFAULT 0.00,
    coupons_info TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Таблиця підписок
CREATE TABLE subscriptions (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    product_id TEXT REFERENCES products(product_id) ON DELETE CASCADE,
    target_price_usd NUMERIC(10, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(telegram_id, product_id)
);

-- Таблиця історії цін
CREATE TABLE price_history (
    id SERIAL PRIMARY KEY,
    product_id TEXT REFERENCES products(product_id) ON DELETE CASCADE,
    price_usd NUMERIC(10, 2) NOT NULL,
    shipping_usd NUMERIC(10, 2) DEFAULT 0.00,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

3. Знайдіть свої облікові дані Supabase в розділі **Project Settings** -> **API**:
   * `Project URL` (це буде ваш `SUPABASE_URL`)
   * `API Key` (це буде ваш `SUPABASE_KEY` - беріть ключ `anon public`)

---

### Крок 2. Налаштування Telegram-бота
1. Напишіть [@BotFather](https://t.me/BotFather) в Telegram та створіть нового бота за допомогою команди `/newbot`.
2. Скопіюйте отриманий токен (`TELEGRAM_BOT_TOKEN`).

---

### Крок 3. Налаштування Gemini API (Очищення назв)
1. Отримайте безкоштовний API ключ у [Google AI Studio](https://aistudio.google.com/).
2. Скопіюйте його (`GEMINI_API_KEY`). *Якщо ви не налаштуєте цей ключ, бот автоматично перейде на спрощений локальний алгоритм чищення назв через регулярні вирази.*

---

### Крок 4. Локальний запуск (для тестування)
Створіть файл `.env` у кореневій директорії проекту та заповніть його:
```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-public-key
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
GEMINI_API_KEY=your-gemini-api-key
```

Встановіть залежності та запустіть бота локально в режимі Long Polling:
```bash
pip install -r requirements.txt
playwright install chromium
python bot_app.py
```

---

### Крок 5. Деплой бота на Vercel (Серверна частина)
1. Створіть новий приватний репозиторій на GitHub та завантажте туди весь код проекту.
2. Зареєструйтеся на [Vercel](https://vercel.com/) за допомогою акаунта GitHub.
3. Імпортуйте створений репозиторій.
4. У налаштуваннях проекту Vercel додайте **Environment Variables** (з такими ж значеннями, як і в `.env`):
   * `SUPABASE_URL`
   * `SUPABASE_KEY`
   * `TELEGRAM_BOT_TOKEN`
   * `GEMINI_API_KEY`
5. Натисніть **Deploy**. Vercel згенерує для вас посилання на деплой (наприклад, `https://aliexpress-price-tracker-bot.vercel.app`).
6. **Налаштуйте Webhook для Telegram**, зробивши запит у браузері або через curl:
   ```text
   https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=<YOUR_VERCEL_URL>/api/webhook
   ```
   *Замініть `<TELEGRAM_BOT_TOKEN>` на токен вашого бота, а `<YOUR_VERCEL_URL>` на згенеровану Vercel адресу.*

---

### Крок 6. Налаштування Cron оновлення цін (GitHub Actions)
1. Відкрийте свій репозиторій на GitHub.
2. Перейдіть до **Settings** -> **Secrets and variables** -> **Actions**.
3. Додайте наступні **Repository secrets** (зверніть увагу, саме в Secrets, а не Variables):
   * `SUPABASE_URL`
   * `SUPABASE_KEY`
   * `TELEGRAM_BOT_TOKEN`
   * `GEMINI_API_KEY`
4. Активуйте розділ **Actions** у своєму репозиторії. За замовчуванням GitHub може вимкнути заплановані воркфлоу в форкнутих або нових репозиторіях — натисніть кнопку "I understand my workflows, go ahead and enable them".
5. Тепер кожні 6 годин GitHub Actions буде запускати перевірку цін. Ви також можете запустити скрипт вручну в розділі **Actions** -> **AliExpress Price Check Cron** -> **Run workflow**.

---

## 📱 Як користуватися ботом
1. Знайдіть свого бота в Telegram та натисніть `/start`.
2. Надішліть йому посилання на товар з AliExpress (наприклад, `https://www.aliexpress.com/item/1005007171007591.html` або мобільне `https://a.aliexpress.com/XXXXXX`).
3. Бот зчитає інформацію про товар, збереже її і покаже ціну в обраній валюті, монети та купони.
4. Після цього бот автоматично проведе пошук та надішле список дешевших аналогів від інших продавців (враховуючи вартість доставки!).
5. За допомогою команди `/settings` ви можете змінити валюту показу цін (USD, UAH або Обидві).
6. За допомогою команди `/list` ви можете побачити всі товари, які ви зараз відстежуєте, а також різницю в ціні.
