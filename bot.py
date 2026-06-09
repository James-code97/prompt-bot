import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# --- Config ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DB_PATH = "prompts.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    row = conn.execute("SELECT content FROM prompts WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row[0] if row else None

def db_list():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT name FROM prompts ORDER BY name").fetchall()
    conn.close()
    return [r[0] for r in rows]

def db_delete(name):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("DELETE FROM prompts WHERE name = ?", (name,))
    conn.commit()
    deleted = cur.rowcount > 0
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
        "*How to use:*\n"
        "/save name \\| your prompt text here\n"
        "/list — List all saved prompts\n"
        "/get name — Retrieve a prompt\n"
        "/find keyword — Search prompts\n"
        "/delete name — Delete a prompt\n\n"
        "*Example:*\n"
        "`/save moodle\\-html \\| Create a clean HTML snippet\\.\\.\\.`"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def save_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /save name | your prompt text\n\n"
            "Example:\n/save moodle-html | Create a clean, professional HTML snippet for Moodle..."
        )
        return

    full_text = " ".join(context.args)
    if "|" not in full_text:
        await update.message.reply_text(
            "⚠️ Use a | to separate name from content.\n\n"
            "Example:\n/save moodle-html | Create a clean, professional HTML snippet..."
        )
        return

    parts = full_text.split("|", 1)
    name = parts[0].strip()
    content = parts[1].strip()

    if not name or not content:
        await update.message.reply_text("⚠️ Both name and content are required.\n\nExample:\n/save moodle-html | Your prompt here...")
        return

    db_save(name, content)
    await update.message.reply_text(f"✅ Prompt saved: *{name}*", parse_mode="Markdown")

async def get_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        names = db_list()
        if not names:
            await update.message.reply_text("📭 No prompts saved yet. Use /save to add one.")
            return
        keyboard = [[InlineKeyboardButton(f"📋 {n}", callback_data=f"get:{n}")] for n in names]
        await update.message.reply_text("Tap a prompt to retrieve:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    name = " ".join(context.args)
    content = db_get(name)
    if content:
        await update.message.reply_text(f"📋 {name}\n\n{content}")
    else:
        await update.message.reply_text(f"❌ No prompt found: {name}")

async def list_prompts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = db_list()
    if not names:
        await update.message.reply_text("📭 No prompts saved yet. Use /save to add one.")
        return
    keyboard = [[InlineKeyboardButton(f"📋 {n}", callback_data=f"get:{n}")] for n in names]
    await update.message.reply_text(f"📚 Your Prompts ({len(names)}):", reply_markup=InlineKeyboardMarkup(keyboard))

async def find_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /find keyword")
        return
    keyword = " ".join(context.args)
    results = db_search(keyword)
    if not results:
        await update.message.reply_text(f"🔍 No prompts matching: {keyword}")
        return
    keyboard = [[InlineKeyboardButton(f"📋 {n}", callback_data=f"get:{n}")] for n in results]
    await update.message.reply_text(f"🔍 Results for '{keyword}':", reply_markup=InlineKeyboardMarkup(keyboard))

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
        await update.message.reply_text(f"🗑️ Deleted: {name}")
    else:
        await update.message.reply_text(f"❌ No prompt found: {name}")

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
            await query.message.reply_text(f"🗑️ Deleted: {name}")
        else:
            await query.message.reply_text(f"❌ Could not delete '{name}'.")

# --- Main ---
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("save", save_prompt))
    app.add_handler(CommandHandler("get", get_prompt))
    app.add_handler(CommandHandler("list", list_prompts))
    app.add_handler(CommandHandler("find", find_prompt))
    app.add_handler(CommandHandler("delete", delete_prompt))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
