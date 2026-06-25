"""
💰 Фінансовий додаток для Railway
З PostgreSQL базою даних
"""

import json
import os
import datetime
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import psycopg2
from psycopg2.extras import RealDictCursor

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, ConversationHandler, filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 8765))
DATABASE_URL = os.environ.get("DATABASE_URL", "")

CHOOSE_DATE, CHOOSE_PERSON, CHOOSE_CATEGORY, ENTER_AMOUNT, ENTER_NOTE = range(5)

CATEGORIES = [
    ["🛒 Продукти", "💆 Краса та здоров'я"],
    ["☕ Кафе", "🏠 Житло"],
    ["🚗 Транспорт", "👗 Одяг"],
    ["🎬 Розваги", "📱 Підписки"],
    ["🏋️ Спорт", "💡 Платіжки"],
    ["🎁 Подарунки", "💳 % по кредиту"],
    ["🏡 Товари для дому", "💼 Товари для роботи"],
    ["🏦 Закриття кредиту", "📦 Інше"],
]

# ---- База даних ----
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id BIGINT PRIMARY KEY,
            person VARCHAR(10),
            category VARCHAR(50),
            amount FLOAT,
            note TEXT DEFAULT '',
            date VARCHAR(10)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id BIGINT PRIMARY KEY,
            name VARCHAR(50) UNIQUE NOT NULL
        )
    """)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM categories")
    count = cur.fetchone()[0]
    if count == 0:
        defaults = [c for row in CATEGORIES for c in row]
        for i, name in enumerate(defaults):
            cur.execute(
                "INSERT INTO categories (id, name) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                (i + 1, name)
            )
        conn.commit()
    cur.close()
    conn.close()
    print("✅ База даних готова")

def load_data():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM expenses ORDER BY date DESC, id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def add_expense(expense):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO expenses (id, person, category, amount, note, date) VALUES (%s, %s, %s, %s, %s, %s)",
        (expense["id"], expense["person"], expense["category"],
         expense["amount"], expense.get("note", ""), expense["date"])
    )
    conn.commit()
    cur.close()
    conn.close()

def delete_expense(eid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM expenses WHERE id = %s", (eid,))
    conn.commit()
    cur.close()
    conn.close()

def load_categories():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM categories ORDER BY id ASC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def add_category(name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM categories")
    new_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO categories (id, name) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
        (new_id, name)
    )
    conn.commit()
    cur.close()
    conn.close()
    return new_id

def delete_category(cid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM categories WHERE id = %s", (cid,))
    conn.commit()
    cur.close()
    conn.close()

def filter_expenses(from_d=None, to_d=None, person=None):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    query = "SELECT * FROM expenses WHERE 1=1"
    params = []
    if from_d:
        query += " AND date >= %s"; params.append(from_d)
    if to_d:
        query += " AND date <= %s"; params.append(to_d)
    if person and person != "all":
        query += " AND person = %s"; params.append(person)
    query += " ORDER BY date DESC, id DESC"
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

# ---- HTTP Сервер ----
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ["/", "/dashboard"]:
            if os.path.exists("dashboard.html"):
                with open("dashboard.html", "r", encoding="utf-8") as f:
                    self.send_html(f.read())
            else:
                self.send_json({"error": "not found"}, 404)
        elif parsed.path == "/expenses":
            self.send_json(load_data())
        elif parsed.path == "/expenses/filter":
            params = parse_qs(parsed.query)
            rows = filter_expenses(
                from_d=params.get("from", [None])[0],
                to_d=params.get("to", [None])[0],
                person=params.get("person", [None])[0]
            )
            self.send_json(rows)
        elif parsed.path == "/categories":
            self.send_json(load_categories())
        elif parsed.path == "/health":
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/expenses":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                expense = json.loads(body.decode("utf-8"))
                expense["id"] = int(datetime.datetime.now().timestamp() * 1000)
                expense.setdefault("note", "")
                add_expense(expense)
                self.send_json({"ok": True, "id": expense["id"]})
            except Exception as ex:
                self.send_json({"error": str(ex)}, 400)
        elif self.path == "/categories":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
                name = (payload.get("name") or "").strip()
                if not name:
                    self.send_json({"error": "empty name"}, 400)
                    return
                new_id = add_category(name)
                self.send_json({"ok": True, "id": new_id, "name": name})
            except Exception as ex:
                self.send_json({"error": str(ex)}, 400)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "expenses":
            try:
                delete_expense(int(parts[1]))
                self.send_json({"ok": True})
            except Exception as ex:
                self.send_json({"error": str(ex)}, 400)
        elif len(parts) == 2 and parts[0] == "categories":
            try:
                delete_category(int(parts[1]))
                self.send_json({"ok": True})
            except Exception as ex:
                self.send_json({"error": str(ex)}, 400)
        else:
            self.send_json({"error": "not found"}, 404)

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"✅ Сервер: http://0.0.0.0:{PORT}")
    server.serve_forever()

# ---- Telegram Bot ----
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привіт! Я твій фінансовий помічник.\n\n"
        "/add — додати витрату\n"
        "/today — сьогодні\n"
        "/week — тиждень\n"
        "/month — місяць\n"
        "/stats — всі витрати"
    )

async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    keyboard = [
        [KeyboardButton(f"📅 Сьогодні ({today.strftime('%d.%m')})"),
         KeyboardButton(f"📅 Вчора ({yesterday.strftime('%d.%m')})")],
        [KeyboardButton("✏️ Ввести дату вручну")],
    ]
    await update.message.reply_text(
        "📅 За яке число витрата?",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return CHOOSE_DATE

async def choose_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    today = datetime.date.today()
    if "Сьогодні" in text:
        ctx.user_data["date"] = today.isoformat()
        ctx.user_data["date_label"] = f"сьогодні ({today.strftime('%d.%m')})"
    elif "Вчора" in text:
        d = today - datetime.timedelta(days=1)
        ctx.user_data["date"] = d.isoformat()
        ctx.user_data["date_label"] = f"вчора ({d.strftime('%d.%m')})"
    elif "Ввести дату вручну" in text:
        await update.message.reply_text("Введіть дату: ДД.ММ", reply_markup=ReplyKeyboardRemove())
        ctx.user_data["awaiting_manual_date"] = True
        return CHOOSE_DATE
    elif ctx.user_data.get("awaiting_manual_date"):
        try:
            parts = text.strip().split(".")
            d = datetime.date(today.year, int(parts[1]), int(parts[0]))
            ctx.user_data["date"] = d.isoformat()
            ctx.user_data["date_label"] = d.strftime('%d.%m.%Y')
            ctx.user_data["awaiting_manual_date"] = False
        except:
            await update.message.reply_text("❌ Формат: 01.06")
            return CHOOSE_DATE
    keyboard = [[KeyboardButton("👤 Женя"), KeyboardButton("👩 Аліна")]]
    await update.message.reply_text(
        f"✅ {ctx.user_data['date_label']}\n\nЧия витрата?",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return CHOOSE_PERSON

async def choose_person(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["person"] = "me" if "Женя" in update.message.text else "wife"
    await update.message.reply_text(
        "Категорія:",
        reply_markup=ReplyKeyboardMarkup(CATEGORIES, resize_keyboard=True, one_time_keyboard=True)
    )
    return CHOOSE_CATEGORY

async def choose_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["category"] = update.message.text
    await update.message.reply_text("Сума (грн):", reply_markup=ReplyKeyboardRemove())
    return ENTER_AMOUNT

async def enter_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["amount"] = float(update.message.text.replace(",", "."))
        await update.message.reply_text("Нотатка (або «-» щоб пропустити):")
        return ENTER_NOTE
    except:
        await update.message.reply_text("❌ Введіть число: 350")
        return ENTER_AMOUNT

async def enter_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    note = "" if update.message.text.strip() == "-" else update.message.text.strip()
    d = ctx.user_data
    expense = {
        "id": int(datetime.datetime.now().timestamp() * 1000),
        "person": d["person"], "category": d["category"],
        "amount": d["amount"], "note": note, "date": d["date"]
    }
    add_expense(expense)
    person_label = "👤 Женя" if d["person"] == "me" else "👩 Аліна"
    await update.message.reply_text(
        f"✅ Збережено!\n📅 {d.get('date_label', d['date'])}\n"
        f"{person_label} | {d['category']} | {d['amount']:.0f} ₴"
        + (f"\n📝 {note}" if note else "") + "\n\nДодати ще? /add"
    )
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Скасовано.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def format_stats(records, title):
    if not records:
        return f"📭 {title}: немає витрат."
    total = sum(r["amount"] for r in records)
    me = sum(r["amount"] for r in records if r["person"] == "me")
    wife = sum(r["amount"] for r in records if r["person"] == "wife")
    cats = {}
    for r in records:
        cats[r["category"]] = cats.get(r["category"], 0) + r["amount"]
    cat_lines = "\n".join(f"  {c}: {a:.0f} ₴ ({a/total*100:.0f}%)"
                          for c, a in sorted(cats.items(), key=lambda x: -x[1]))
    return f"📊 *{title}*\n\n💰 Всього: *{total:.0f} ₴*\n👤 Женя: {me:.0f} ₴\n👩 Аліна: {wife:.0f} ₴\n\n*Категорії:*\n{cat_lines}"

async def today_stats(update, ctx):
    records = filter_expenses(from_d=datetime.date.today().isoformat(), to_d=datetime.date.today().isoformat())
    await update.message.reply_text(format_stats(records, "Сьогодні"), parse_mode="Markdown")

async def week_stats(update, ctx):
    cutoff = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    records = filter_expenses(from_d=cutoff)
    await update.message.reply_text(format_stats(records, "За тиждень"), parse_mode="Markdown")

async def month_stats(update, ctx):
    cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    records = filter_expenses(from_d=cutoff)
    await update.message.reply_text(format_stats(records, "За місяць"), parse_mode="Markdown")

async def all_stats(update, ctx):
    await update.message.reply_text(format_stats(load_data(), "Всі витрати"), parse_mode="Markdown")

def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            CHOOSE_DATE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_date)],
            CHOOSE_PERSON:   [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_person)],
            CHOOSE_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_category)],
            ENTER_AMOUNT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
            ENTER_NOTE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_note)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("today", today_stats))
    app.add_handler(CommandHandler("week", week_stats))
    app.add_handler(CommandHandler("month", month_stats))
    app.add_handler(CommandHandler("stats", all_stats))
    app.add_handler(conv)
    print("🤖 Бот запущено...")
    app.run_polling()

if __name__ == "__main__":
    import time
    init_db()
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    # Запускаємо бота з автоперезапуском при помилці
    while True:
        try:
            import asyncio
            asyncio.set_event_loop(asyncio.new_event_loop())
            run_bot()
        except Exception as e:
            print(f"⚠️ Бот впав: {e}, перезапуск через 10 сек...")
            time.sleep(10)
