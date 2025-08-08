
import asyncio
import logging
import os
import random
import sqlite3
import string
import re
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("purchase-bot")

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
PAYMENT_DETAILS_UK = os.getenv("PAYMENT_DETAILS_UK", "Payment details not set for UK")
PAYMENT_DETAILS_DE = os.getenv("PAYMENT_DETAILS_DE", "Payment details not set for DE")

DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")

# --- Simple SQLite helpers ---
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY,
              tg_user_id INTEGER UNIQUE,
              username TEXT,
              first_name TEXT,
              last_name TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders(
              id INTEGER PRIMARY KEY,
              tg_user_id INTEGER,
              country TEXT,
              status TEXT,
              photo_file_id TEXT,
              created_at TEXT
            )
        """)

def upsert_user(u):
    with db() as conn:
        conn.execute("""
            INSERT INTO users (tg_user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(tg_user_id) DO UPDATE SET
              username=excluded.username,
              first_name=excluded.first_name,
              last_name=excluded.last_name
        """, (u.id, u.username, u.first_name, u.last_name))

def get_user_by_tg_id(tg_user_id: int) -> Optional[sqlite3.Row]:
    with db() as conn:
        cur = conn.execute("SELECT * FROM users WHERE tg_user_id=?", (tg_user_id,))
        return cur.fetchone()

def display_name_from_row(row: sqlite3.Row) -> str:
    first = (row.get("first_name") if isinstance(row, dict) else row["first_name"]) or ""
    last = (row.get("last_name") if isinstance(row, dict) else row["last_name"]) or ""
    name = (first + " " + last).strip()
    return name if name else "customer"

def slugify_name(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^a-z0-9_]+", "", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "user"

def create_order(tg_user_id: int, country: str) -> int:
    with db() as conn:
        cur = conn.execute("""
            INSERT INTO orders (tg_user_id, country, status, created_at)
            VALUES (?, ?, 'AWAITING_PAYMENT', ?)
        """, (tg_user_id, country, datetime.utcnow().isoformat()))
        return cur.lastrowid

def set_order_screenshot(order_id: int, photo_file_id: str):
    with db() as conn:
        conn.execute("UPDATE orders SET photo_file_id=?, status='PENDING_APPROVAL' WHERE id=?", (photo_file_id, order_id))

def set_order_status(order_id: int, status: str):
    with db() as conn:
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))

def get_order(order_id: int):
    with db() as conn:
        cur = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        return cur.fetchone()

# --- Conversation states ---
CHOOSING_COUNTRY, AWAITING_SCREENSHOT = range(2)

# --- Utilities ---
def generate_username(country: str, display_name: str) -> str:
    base = slugify_name(display_name)
    tail = "".join(random.choices(string.digits, k=2))  # exactly 2 digits
    return f"{base}_{tail}"

def generate_password() -> str:
    # Per request: default "1". Consider stronger passwords for production.
    return "1"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)
    text = (
        "Hello! I’m your assistant for private login.\n\n"
        "Use the command /buy to get started quickly.\n\n"
        "Select UK or Germany, view payment info, make payment and upload your payment screenshot.\n\n"
        "Once approved by the admin, your login details will be sent to you."
    )
    await update.message.reply_text(text)



async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Hello! I’m your assistant for private login.

"
        "Use the command /buy to get started quickly.

"
        "How it works:
"
        "1) Select UK or Germany.
"
        "2) View payment info.
"
        "3) Make payment & upload your screenshot.
"
        "4) Wait for admin approval.
"
        "5) Receive your login details."
    )
    await update.message.reply_text(text)
    # Added support info to help text
    text += \"\n\nFor support: Message @techafresh_bot or @marshallcc_bot\"


async def support_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Message our bot support @techafresh_bot or @marshallcc_bot "
        "for all enquiries & purchases."
    )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Hello! I’m your assistant for private login.\n\n"
        "Use the command /buy to get started quickly.\n\n"
        "Steps to get access:\n"
        "1. Select UK or Germany.\n"
        "2. View payment info.\n"
        "3. Make payment & upload your screenshot.\n"
        "4. Wait for admin approval.\n"
        "5. Receive your login details."
    )
    await update.message.reply_text(help_text)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. If you change your mind, type /buy.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)

    keyboard = [
        [InlineKeyboardButton("🇬🇧 UK", callback_data="country:UK"),
         InlineKeyboardButton("🇩🇪 Germany", callback_data="country:DE")]
    ]
    await update.message.reply_text(
        "Choose your server location (required before payment):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSING_COUNTRY

async def choose_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")[1]  # "UK" or "DE"
    context.user_data["country"] = data

    payment_text = PAYMENT_DETAILS_UK if data == "UK" else PAYMENT_DETAILS_DE
    await query.edit_message_text(
        f"You chose *{data}*.\n\n"
        f"Please send payment to:\n\n"
        f"{payment_text}\n\n"
        "When done, upload a clear *screenshot* of your payment here.",
        parse_mode="Markdown",
    )

    # Create order in DB
    order_id = create_order(query.from_user.id, data)
    context.user_data["order_id"] = order_id
    return AWAITING_SCREENSHOT

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Please upload a *screenshot* image (not other file types).", parse_mode="Markdown")
        return AWAITING_SCREENSHOT

    photo = update.message.photo[-1]  # highest resolution
    file_id = photo.file_id

    order_id = context.user_data.get("order_id")
    country = context.user_data.get("country", "UK")

    if not order_id:
        # In rare cases state lost
        order_id = create_order(update.effective_user.id, country)
        context.user_data["order_id"] = order_id

    set_order_screenshot(order_id, file_id)

    # Forward to admin for approval
    caption = (
        f"Payment screenshot from @{update.effective_user.username or 'unknown'}\n"
        f"Order ID: {order_id}\n"
        f"Country: {country}\n"
        f"Approve?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{order_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{order_id}"),
        ]
    ]

    try:
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=file_id,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        log.exception("Failed to send to admin: %s", e)
        await update.message.reply_text("Thanks! I couldn't reach the admin – please try again later.")
        return ConversationHandler.END

    await update.message.reply_text("Thanks! Your payment is pending admin review. You'll get a reply here when it's approved.")
    return ConversationHandler.END

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin Approve/Reject buttons."""
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_CHAT_ID:
        await query.edit_message_caption(caption="Not authorized.")
        return

    action, order_id_str = query.data.split(":")
    order_id = int(order_id_str)
    order = get_order(order_id)
    if not order:
        await query.edit_message_caption(caption="Order not found.")
        return

    user_id = order["tg_user_id"]
    country = order["country"]

    if action == "approve":
        set_order_status(order_id, "APPROVED")

        # Build username from the user's Telegram display name (no country prefix)
        urow = get_user_by_tg_id(user_id)
        disp = display_name_from_row(urow) if urow else "customer"
        username = generate_username(country, disp)
        password = generate_password()

        # Simulate provisioning (replace with your API call)
        await asyncio.sleep(0.5)

        # Send credentials to the buyer
        creds = (
            f"✅ Your payment is approved!\n\n"
            f"**Server:** {country}\n"
            f"**Username:** `{username}`\n"
            f"**Password:** `{password}`\n\n"
            f"Please change your password on first login if supported."
        )
        await context.bot.send_message(chat_id=user_id, text=creds, parse_mode="Markdown")

        await query.edit_message_caption(caption=f"Order {order_id}: Approved and credentials sent.")
    elif action == "reject":
        set_order_status(order_id, "REJECTED")
        await context.bot.send_message(chat_id=user_id, text="❌ Your payment was not approved. If you think this is a mistake, reply with /buy to try again.")
        await query.edit_message_caption(caption=f"Order {order_id}: Rejected.")
    else:
        await query.edit_message_caption(caption="Unknown action.")

async def unknown_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("If you're trying to buy, use /buy and then send the screenshot when asked.")

def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("buy", buy)],
        states={
            CHOOSING_COUNTRY: [CallbackQueryHandler(choose_country, pattern=r"^country:(UK|DE)$")],
            AWAITING_SCREENSHOT: [MessageHandler(filters.PHOTO, receive_screenshot)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("support", support_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(conv)

    # Admin actions
    app.add_handler(CallbackQueryHandler(admin_action, pattern=r"^(approve|reject):\d+$"))

    # Catch photos outside the flow
    app.add_handler(MessageHandler(filters.PHOTO, unknown_photo))

    return app

if __name__ == "__main__":
    init_db()
    if not BOT_TOKEN or ADMIN_CHAT_ID == 0:
        log.error("Please set BOT_TOKEN and ADMIN_CHAT_ID in your .env")
        raise SystemExit(1)

    app = build_app()
    log.info("Bot starting (polling). Press Ctrl+C to stop.")
    app.run_polling()
