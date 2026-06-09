import os
import json
import base64
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# --- Config ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = "prompts.json"
GITHUB_BRANCH = "main"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- GitHub JSON Storage ---
def _github_url():
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

def _headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

def _load_prompts():
    try:
        logger.info(f"Loading prompts from GitHub: {GITHUB_REPO}")
        r = requests.get(_github_url(), headers=_headers(), params={"ref": GITHUB_BRANCH}, timeout=10)
        logger.info(f"GitHub GET status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data["sha"]
        elif r.status_code == 404:
            logger.info("prompts.json not found, starting fresh")
            return {}, None
        else:
            logger.error(f"GitHub load error: {r.status_code} {r.text}")
            return {}, None
    except requests.exceptions.Timeout:
        logger.error("GitHub request timed out")
        return {}, None
    except Exception as e:
        logger.error(f"GitHub load exception: {e}")
        return {}, None

def _save_prompts(prompts, sha=None):
    try:
        content = base64.b64encode(json.dumps(prompts, indent=2, ensure_ascii=False).encode("utf-8")).decode("utf-8")
        payload = {
            "message": "Update prompts",
            "content": content,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha
        logger.info(f"Saving prompts to GitHub, sha={sha}")
        r = requests.put(_github_url(), headers=_headers(), json=payload, timeout=10)
        logger.info(f"GitHub PUT status: {r.status_code}")
        if r.status_code in (200, 201):
            return True
        else:
            logger.error(f"GitHub save error: {r.status_code} {r.text}")
            return False
    except requests.exceptions.Timeout:
        logger.error("GitHub save request timed out")
        return False
    except Exception as e:
        logger.error(f"GitHub save exception: {e}")
        return False

def db_save(name, content):
    prompts, sha = _load_prompts()
    prompts[name] = content
    return _save_prompts(prompts, sha)

def db_get(name):
    prompts, _ = _load_prompts()
    return prompts.get(name)

def db_list():
    prompts, _ = _load_prompts()
    return sorted(prompts.keys())

def db_delete(name):
    prompts, sha = _load_prompts()
    if name in prompts:
        del prompts[name]
        return _save_prompts(prompts, sha)
    return False

def db_search(keyword):
    prompts, _ = _load_prompts()
    keyword_lower = keyword.lower()
    return sorted([n for n in prompts if keyword_lower in n.lower()])

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
        await update.message.reply_text("⚠️ Both name and content are required.")
        return

    if db_save(name, content):
        await update.message.reply_text(f"✅ Prompt saved: {name}")
    else:
        await update.message.reply_text("❌ Error saving. Check bot logs.")

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
        # Split long messages (Telegram 4096 char limit)
        header = f"📋 {name}\n\n"
        if len(header + content) > 4096:
            await update.message.reply_text(header)
            for i in range(0, len(content), 4096):
                await update.message.reply_text(content[i:i+4096])
        else:
            await update.message.reply_text(f"📋 {name}\n\n{content}")
    else:
        await update.message.reply_text(f"❌ No prompt found: {name}")

async def list_prompts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        names = db_list()
        if not names:
            await update.message.reply_text("📭 No prompts saved yet. Use /save to add one.")
            return
        keyboard = [[InlineKeyboardButton(f"📋 {n}", callback_data=f"get:{n}")] for n in names]
        await update.message.reply_text(f"📚 Your Prompts ({len(names)}):", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"list_prompts error: {e}")
        await update.message.reply_text(f"❌ Error loading list: {e}")

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
            header = f"📋 {name}\n\n"
            if len(header + content) > 4096:
                await query.message.reply_text(header)
                for i in range(0, len(content), 4096):
                    await query.message.reply_text(content[i:i+4096])
            else:
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
