import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

# --- Config ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DB_PATH = "prompts.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Conversation states ---
WAITING_FOR_NAME = 1
WAITING_FOR_PROMPT = 2

# --- Database ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def db_save(name, content):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT OR REPLACE INTO prompts (name, content) VALUES (?, ?)", (name, content))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"DB save error: {e}")
        return False
    finally:
        conn.close()

def db_get(name):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT content FROM prompts WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
    conn.close()
    return row[0] if row else None

def db_list():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT name FROM prompts ORDER BY name").fetchall()
    conn.close()
    return [r[0] for r in rows]

def db_delete(name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("DELETE FROM prompts WHERE LOWER(name) = LOWER(?)", (name,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted

def db_search(keyword):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT name FROM prompts WHERE LOWER(name) LIKE LOWER(?) ORDER BY name",
        (f"%{keyword}%",)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 *Prompt Manager Bot*\n\n"
        "Store and retrieve your prompts anytime\\.\n\n"
        "*Commands:*\n"
        "/save — Save a new prompt\n"
        "/list — List all saved prompts\n"
        "/get `name` — Retrieve a prompt\n"
        "/find `keyword` — Search prompts\n"
        "/delete `name` — Delete a prompt\n"
        "/help — Show this message"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# --- Save flow (conversation) ---

async def save_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 *What name for this prompt?*\n\nType a short name (e.g. `moodle-quiz`, `email-template`).", parse_mode="MarkdownV2")
    return WAITING_FOR_NAME

async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Name can't be empty. Try again:")
        return WAITING_FOR_NAME
    context.user_data["prompt_name"] = name
    await update.message.reply_text(f"✅ Name: *{name}*\n\nNow paste the prompt content:", parse_mode="Markdown")
    return WAITING_FOR_PROMPT

async def save_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("prompt_name")
    content = update.message.text.strip()
    if not content:
        await update.message.reply_text("❌ Prompt can't be empty. Paste your prompt:")
        return WAITING_FOR_PROMPT
    if db_save(name, content):
        await update.message.reply_text(f"✅ Prompt *{name}* saved\\!", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text("❌ Error saving. Please try again.")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# --- Get ---

async def get_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        # Show list with buttons
        names = db_list()
        if not names:
            await update.message.reply_text("📭 No prompts saved yet. Use /save to add one.")
            return
        keyboard = [[InlineKeyboardButton(n, callback_data=f"get:{n}")] for n in names]
        await update.message.reply_text("Tap a prompt to retrieve:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    name = " ".join(context.args)
    content = db_get(name)
    if content:
        # Send as plain text so user can copy easily
        await update.message.reply_text(f"📋 {name}\n\n{content}")
    else:
        await update.message.reply_text(f"❌ No prompt found with name: *{name}*", parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("get:"):
        name = data[4:]
        content = db_get(name)
        if content:
            await query.message.reply_text(f"📋 {name}\n\n{content}")
        else:
            await query.message.reply_text(f"❌ Prompt '{name}' not found.")

    elif data.startswith("del:"):
        name = data[4:]
        if db_delete(name):
            await query.message.reply_text(f"🗑️ Deleted: *{name}*", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ Could not delete '{name}'.")

# --- List ---

async def list_prompts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = db_list()
    if not names:
        await update.message.reply_text("📭 No prompts saved yet. Use /save to add one.")
        return
    keyboard = [[InlineKeyboardButton(f"📋 {n}", callback_data=f"get:{n}")] for n in names]
    await update.message.reply_text(
        f"📚 *Your Prompts ({len(names)}):*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- Search ---

async def find_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /find `keyword`", parse_mode="Markdown")
        return
    keyword = " ".join(context.args)
    results = db_search(keyword)
    if not results:
        await update.message.reply_text(f"🔍 No prompts matching: *{keyword}*", parse_mode="Markdown")
        return
    keyboard = [[InlineKeyboardButton(f"📋 {n}", callback_data=f"get:{n}")] for n in results]
    await update.message.reply_text(
        f"🔍 Results for *{keyword}*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- Delete ---

async def delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        names = db_list()
        if not names:
            await update.message.reply_text("📭 No prompts to delete.")
            return
        keyboard = [[InlineKeyboardButton(f"🗑️ {n}", callback_data=f"del:{n}")] for n in names]
        await update.message.reply_text("Tap a prompt to delete:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    name = " ".join(context.args)
    if db_delete(name):
        await update.message.reply_text(f"🗑️ Deleted: *{name}*", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ No prompt found: *{name}*", parse_mode="Markdown")

# --- Main ---

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Save conversation
    save_handler = ConversationHandler(
        entry_points=[CommandHandler("save", save_start)],
        states={
            WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)],
            WAITING_FOR_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_content)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(save_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("get", get_prompt))
    app.add_handler(CommandHandler("list", list_prompts))
    app.add_handler(CommandHandler("find", find_prompt))
    app.add_handler(CommandHandler("delete", delete_prompt))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
