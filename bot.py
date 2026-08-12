import logging
import sys
import re
import asyncio
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import config
import database as db

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- KEYBOARDS ---

def get_main_keyboard(is_admin: bool = False):
    keyboard = [
        [KeyboardButton("🏠 Main Menu"), KeyboardButton("📱 Get Numbers")],
        [KeyboardButton("🔄 Change Number"), KeyboardButton("💰 Balance")],
        [KeyboardButton("📊 My Stats"), KeyboardButton("💸 Withdraw")],
        [KeyboardButton("📋 My Numbers"), KeyboardButton("ℹ️ Help")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton("👨‍💼 Admin Menu")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    keyboard = [
        [KeyboardButton("📦 Stock"), KeyboardButton("📤 Upload Stock")],
        [KeyboardButton("🗑 Remove Stock"), KeyboardButton("💰 Reward Prices")],
        [KeyboardButton("📢 Broadcast"), KeyboardButton("👥 Required Groups")],
        [KeyboardButton("🏷 Reward Group"), KeyboardButton("💸 Withdrawals")],
        [KeyboardButton("📊 Statistics"), KeyboardButton("🏠 Main Menu")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- USER HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = user.id in config.ADMIN_IDS
    db_user = db.get_or_create_user(user.id, user.username or user.first_name)
    
    welcome_msg = (
        f"👋 Welcome to Reward Group\n"
        f"💰 Balance: ${db_user['balance']:.3f}"
    )
    await update.message.reply_text(welcome_msg, reply_markup=get_main_keyboard(is_admin))

async def handle_user_text_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    is_admin = user_id in config.ADMIN_IDS
    db_user = db.get_or_create_user(user_id, update.effective_user.username or "")

    if text == "🏠 Main Menu":
        await update.message.reply_text(f"👋 Main Menu\n💰 Balance: ${db_user['balance']:.3f}", reply_markup=get_main_keyboard(is_admin))
        
    elif text == "📱 Get Numbers":
        inline_kb = [
            [InlineKeyboardButton("🔷 WhatsApp • 266", callback_data="svc_whatsapp")],
            [InlineKeyboardButton("🔷 Telegram • 120", callback_data="svc_telegram")],
            [InlineKeyboardButton("🟣 Other Service • 2", callback_data="svc_other")]
        ]
        await update.message.reply_text("📱 Select a Service:", reply_markup=InlineKeyboardMarkup(inline_kb))

    elif text in ["🔄 Change Number", "🔄 Change Numbers"]:
        assigned = db.assign_numbers(user_id, service="whatsapp", count=3)
        await display_assigned_numbers(update, context, assigned)

    elif text == "💰 Balance":
        balance_msg = (
            f"💰 *Your Balance*\n\n"
            f"Available: ${db_user['balance']:.3f}\n"
            f"Total Earned: ${db_user['total_earned']:.3f}\n"
            f"Total Withdrawn: ${db_user['total_withdrawn']:.3f}\n\n"
            f"_USD ONLY._"
        )
        await update.message.reply_text(balance_msg, parse_mode="Markdown")

    elif text == "📊 My Stats":
        stats_msg = (
            f"📊 *My Stats*\n\n"
            f"📱 Numbers Received: 25\n"
            f"🎯 Numbers Rewarded: 18\n"
            f"💵 Total Earned: ${db_user['total_earned']:.3f}\n"
            f"💸 Total Withdrawn: ${db_user['total_withdrawn']:.3f}\n"
            f"💰 Current Balance: ${db_user['balance']:.3f}"
        )
        await update.message.reply_text(stats_msg, parse_mode="Markdown")

    elif text == "📋 My Numbers":
        numbers = db.get_user_assigned_numbers(user_id)
        if not numbers:
            await update.message.reply_text("📋 No active numbers assigned. Click 'Get Numbers' to request stock.")
            return
        await display_assigned_numbers(update, context, numbers)

    elif text == "💸 Withdraw":
        await update.message.reply_text(
            f"💸 *Withdraw*\n\nCurrent USD Balance: ${db_user['balance']:.3f}\n\n"
            "Reply with your withdrawal method and details (e.g. USDT TRC20: address)",
            parse_mode="Markdown"
        )

    elif text == "ℹ️ Help":
        help_text = (
            "ℹ️ *Help & Usage Information*\n\n"
            "• *Get Numbers*: Request available phone numbers for chosen services.\n"
            "• *Copy Numbers*: Tap direct numbers in message to copy.\n"
            "• *Rewards*: Automatic payout when OTP arrives in configured Reward Group.\n"
            "• *Change Numbers*: Release assigned numbers and fetch new ones.\n"
            "• *Withdraw*: Minimum threshold apply. Submit details for admin review."
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    elif text == "👨‍💼 Admin Menu" and is_admin:
        await update.message.reply_text("👨‍💼 Admin Control Panel", reply_markup=get_admin_keyboard())

# --- NUMBER DISPLAY ---

async def display_assigned_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, numbers: list):
    if not numbers:
        msg = "No stock available for this selection."
        if update.callback_query:
            await update.callback_query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    num_list_text = "\n".join([f"📱 `{n['phone_number']}`" for n in numbers])
    text = f"📱 *ASSIGNED NUMBERS*\n\n{num_list_text}\n\nRemaining stock: 98"

    inline_buttons = []
    for n in numbers:
        phone = n['phone_number']
        inline_buttons.append([
            InlineKeyboardButton(
                text=f"📋 {phone}",
                callback_data=f"copy_{phone}"
            )
        ])
    
    inline_buttons.append([InlineKeyboardButton("🔄 Change Numbers", callback_data="act_change")])
    inline_buttons.append([
        InlineKeyboardButton("🌍 Change Country", callback_data="act_country"),
        InlineKeyboardButton("⚙️ Change Service", callback_data="act_service")
    ])
    inline_buttons.append([InlineKeyboardButton("📨 View Reward Group", url="https://t.me")])

    reply_markup = InlineKeyboardMarkup(inline_buttons)
    
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# --- CALLBACK QUERY ROUTER ---

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if data.startswith("copy_"):
        copied_num = data.replace("copy_", "")
        await query.answer(f"Copied: {copied_num}", show_alert=False)
        return

    await query.answer()

    if data.startswith("svc_") or data == "act_change":
        assigned = db.assign_numbers(user_id, service="whatsapp", count=3)
        await display_assigned_numbers(update, context, assigned)
    elif data == "act_country":
        await query.message.reply_text("Select Country:\n1. 🇳🇬 Nigeria\n2. 🇧🇴 Bolivia")
    elif data == "act_service":
        await query.message.reply_text("Select Service:\n1. WhatsApp\n2. Telegram\n3. Bolt")

# --- GROUP REWARD LISTENER ---

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    result = db.match_and_reward_number(text)

    if result:
        matched_stock, reward_price, phone = result
        credited_user_id = matched_stock['assigned_user_id']
        
        db_user = db.get_or_create_user(credited_user_id, "")
        
        notify_msg = (
            f"🎉 *Reward Received!*\n\n"
            f"📱 Number: `{phone}`\n"
            f"💵 Reward: ${reward_price:.3f}\n"
            f"💰 New Balance: ${db_user['balance']:.3f}"
        )
        try:
            await context.bot.send_message(
                chat_id=credited_user_id,
                text=notify_msg,
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Failed to notify user {credited_user_id}: {e}")

# --- MAIN ENGINE ---

def main():
    if not config.BOT_TOKEN:
        logging.critical("❌ ERROR: BOT_TOKEN is empty! Set BOT_TOKEN in Render Environment Settings.")
        sys.exit(1)

    # Explicit event loop setup for modern Python versions
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    db.init_db()
    
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, handle_user_text_menu))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, handle_group_message))

    logging.info("🚀 Bot is running and connected to Telegram!")
    app.run_polling()

if __name__ == "__main__":
    main()
        
