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
    CallbackQueryHandler, ContextTypes, filters,
    ConversationHandler
)
import config
import database as db

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONVERSATION STATES ---
WAIT_FOR_STOCK = 1
WAIT_FOR_REMOVE_STOCK = 2
WAIT_FOR_BROADCAST = 3
WAIT_FOR_WITHDRAW_AMOUNT = 4
WAIT_FOR_WITHDRAW_DETAILS = 5
WAIT_FOR_PRICES = 6
WAIT_FOR_REQ_GROUP = 7
WAIT_FOR_REW_GROUP = 8

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
        prices = db.get_prices()
        inline_kb = [
            [InlineKeyboardButton(f"🔷 WhatsApp • ${prices.get('whatsapp', 0.5):.2f}", callback_data="svc_whatsapp")],
            [InlineKeyboardButton(f"🔷 Telegram • ${prices.get('telegram', 0.3):.2f}", callback_data="svc_telegram")],
            [InlineKeyboardButton(f"🟣 Other Service • ${prices.get('other', 0.2):.2f}", callback_data="svc_other")]
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
        u_stats = db.get_user_stats(user_id)
        stats_msg = (
            f"📊 *My Stats*\n\n"
            f"📱 Numbers Received: {u_stats['received']}\n"
            f"🎯 Numbers Rewarded: {u_stats['rewarded']}\n"
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

    elif text == "ℹ️ Help":
        req_gp = db.get_setting("required_group", "Not Configured")
        rew_gp = db.get_setting("reward_group", "Not Configured")
        help_text = (
            "ℹ️ *Help & Usage Information*\n\n"
            "• *Get Numbers*: Request available phone numbers for chosen services.\n"
            "• *Copy Numbers*: Tap direct numbers in message to copy.\n"
            "• *Rewards*: Automatic payout when OTP arrives in configured Reward Group.\n"
            "• *Change Numbers*: Release assigned numbers and fetch new ones.\n"
            f"• *Required Group*: {req_gp}\n"
            f"• *Reward Group*: {rew_gp}"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    elif text == "👨‍💼 Admin Menu" and is_admin:
        await update.message.reply_text("👨‍💼 Admin Control Panel", reply_markup=get_admin_keyboard())

    # --- ADMIN SIMPLE MENU BUTTONS ---
    elif text == "📦 Stock" and is_admin:
        summary = db.get_stock_summary()
        msg = "📦 *Current Stock Summary*\n\n"
        if not summary:
            msg += "No stock found in database."
        else:
            for svc, counts in summary.items():
                msg += f"🔹 *{svc.upper()}*\n  • Available: `{counts.get('available', 0)}`\n  • Assigned: `{counts.get('assigned', 0)}`\n  • Rewarded: `{counts.get('rewarded', 0)}`\n\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == "📊 Statistics" and is_admin:
        st = db.get_admin_stats()
        msg = (
            f"📊 *System Statistics*\n\n"
            f"👥 Total Users: `{st['users']}`\n"
            f"📱 Available Stock: `{st['available_stock']}`\n"
            f"🎯 Rewarded OTPs: `{st['rewarded_stock']}`\n"
            f"💸 Total Paid Out: `${st['total_payouts']:.2f}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == "💸 Withdrawals" and is_admin:
        pending = db.get_pending_withdrawals()
        if not pending:
            await update.message.reply_text("✅ No pending withdrawal requests.")
            return
        
        for w in pending:
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"w_app_{w['id']}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"w_rej_{w['id']}")
                ]
            ])
            msg = (
                f"💸 *Withdrawal Request #{w['id']}*\n\n"
                f"👤 User ID: `{w['user_id']}`\n"
                f"💵 Amount: `${w['amount']:.2f}`\n"
                f"📝 Details: `{w['details']}`\n"
                f"📅 Date: `{w['created_at']}`"
            )
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)

# --- CONVERSATION FLOWS (ADMIN & USER) ---

# 1. Stock Upload Flow
async def upload_stock_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in config.ADMIN_IDS:
        return ConversationHandler.END
    await update.message.reply_text("📤 *Upload Stock*\n\nSend numbers (text or .txt file):\nType `cancel` to abort.", parse_mode="Markdown")
    return WAIT_FOR_STOCK

async def process_stock_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = ""
    if update.message.text:
        if update.message.text.lower() == "cancel":
            await update.message.reply_text("❌ Cancelled.", reply_markup=get_admin_keyboard())
            return ConversationHandler.END
        raw_text = update.message.text
    elif update.message.document:
        doc = update.message.document
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        raw_text = file_bytes.decode("utf-8", errors="ignore")

    numbers = re.findall(r'\+?\d{7,15}', raw_text)
    if not numbers:
        await update.message.reply_text("⚠️ No valid numbers found. Try again or type `cancel`.")
        return WAIT_FOR_STOCK

    added = db.add_stock_bulk(numbers)
    await update.message.reply_text(f"✅ Added `{added}` new numbers to stock.", parse_mode="Markdown", reply_markup=get_admin_keyboard())
    return ConversationHandler.END

# 2. Stock Remove Flow
async def remove_stock_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in config.ADMIN_IDS:
        return ConversationHandler.END
    await update.message.reply_text("🗑 *Remove Stock*\n\nSend numbers to remove from stock:\nType `cancel` to abort.", parse_mode="Markdown")
    return WAIT_FOR_REMOVE_STOCK

async def process_remove_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.lower() == "cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    numbers = re.findall(r'\+?\d{7,15}', update.message.text)
    removed = db.remove_stock_bulk(numbers)
    await update.message.reply_text(f"🗑 Removed `{removed}` numbers from stock.", parse_mode="Markdown", reply_markup=get_admin_keyboard())
    return ConversationHandler.END

# 3. Broadcast Flow
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in config.ADMIN_IDS:
        return ConversationHandler.END
    await update.message.reply_text("📢 *Broadcast Message*\n\nSend the message you want to broadcast to all users:\nType `cancel` to abort.", parse_mode="Markdown")
    return WAIT_FOR_BROADCAST

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.lower() == "cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    user_ids = db.get_all_user_ids()
    sent, failed = 0, 0
    await update.message.reply_text(f"⏳ Sending broadcast to {len(user_ids)} users...")

    for uid in user_ids:
        try:
            await context.bot.copy_message(chat_id=uid, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await update.message.reply_text(f"📢 *Broadcast Complete*\n\n✅ Delivered: `{sent}`\n❌ Failed: `{failed}`", parse_mode="Markdown", reply_markup=get_admin_keyboard())
    return ConversationHandler.END

# 4. Withdraw Flow (User)
async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user = db.get_or_create_user(update.effective_user.id, "")
    if db_user['balance'] <= 0:
        await update.message.reply_text("❌ You have zero balance to withdraw.")
        return ConversationHandler.END

    await update.message.reply_text(f"💸 *Withdrawal*\nYour Balance: `${db_user['balance']:.2f}`\n\nEnter amount to withdraw (USD):\nType `cancel` to abort.", parse_mode="Markdown")
    return WAIT_FOR_WITHDRAW_AMOUNT

async def process_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.lower() == "cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    try:
        amount = float(update.message.text.replace("$", ""))
        db_user = db.get_or_create_user(update.effective_user.id, "")
        if amount <= 0 or amount > db_user['balance']:
            await update.message.reply_text("⚠️ Invalid amount or exceeds balance. Enter valid amount:")
            return WAIT_FOR_WITHDRAW_AMOUNT
        
        context.user_data['withdraw_amount'] = amount
        await update.message.reply_text("📝 Send withdrawal payment details (e.g., USDT TRC20 address or Binance Pay ID):")
        return WAIT_FOR_WITHDRAW_DETAILS
    except ValueError:
        await update.message.reply_text("⚠️ Enter numbers only. Try again:")
        return WAIT_FOR_WITHDRAW_AMOUNT

async def process_withdraw_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    details = update.message.text
    amount = context.user_data.get('withdraw_amount', 0)
    
    success, msg = db.create_withdrawal(update.effective_user.id, amount, details)
    await update.message.reply_text(f"✅ {msg}" if success else f"❌ {msg}", reply_markup=get_main_keyboard())
    return ConversationHandler.END

# 5. Reward Prices Flow (Admin)
async def reward_prices_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in config.ADMIN_IDS:
        return ConversationHandler.END
    prices = db.get_prices()
    msg = (
        f"💰 *Current Reward Prices*\n\n"
        f"• WhatsApp: `${prices.get('whatsapp', 0.5):.2f}`\n"
        f"• Telegram: `${prices.get('telegram', 0.3):.2f}`\n"
        f"• Other: `${prices.get('other', 0.2):.2f}`\n\n"
        "Send new prices in format: `whatsapp=0.6, telegram=0.4, other=0.2` or type `cancel`:"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return WAIT_FOR_PRICES

async def process_reward_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.lower() == "cancel":
        await update.message.reply_text("❌ Cancelled.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    try:
        current = db.get_prices()
        pairs = text.split(",")
        for pair in pairs:
            k, v = pair.split("=")
            current[k.strip().lower()] = float(v.strip())
        db.set_prices(current)
        await update.message.reply_text("✅ Reward prices updated successfully!", reply_markup=get_admin_keyboard())
    except Exception:
        await update.message.reply_text("⚠️ Invalid format. Example: `whatsapp=0.6, telegram=0.4` or type `cancel`:")
        return WAIT_FOR_PRICES

    return ConversationHandler.END

# 6. Group Links Configuration
async def req_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in config.ADMIN_IDS:
        return ConversationHandler.END
    await update.message.reply_text("👥 Send required group link/username (e.g., https://t.me/yourgroup) or `cancel`:")
    return WAIT_FOR_REQ_GROUP

async def process_req_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.lower() != "cancel":
        db.set_setting("required_group", update.message.text.strip())
        await update.message.reply_text("✅ Required Group updated!", reply_markup=get_admin_keyboard())
    return ConversationHandler.END

async def rew_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in config.ADMIN_IDS:
        return ConversationHandler.END
    await update.message.reply_text("🏷 Send Reward Group link/username or `cancel`:")
    return WAIT_FOR_REW_GROUP

async def process_rew_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.lower() != "cancel":
        db.set_setting("reward_group", update.message.text.strip())
        await update.message.reply_text("✅ Reward Group updated!", reply_markup=get_admin_keyboard())
    return ConversationHandler.END

async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Action cancelled.")
    return ConversationHandler.END

# --- NUMBER DISPLAY & CALLBACKS ---

async def display_assigned_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, numbers: list):
    if not numbers:
        msg = "No stock available for this selection."
        if update.callback_query:
            await update.callback_query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    num_list_text = "\n".join([f"📱 `{n['phone_number']}`" for n in numbers])
    text = f"📱 *ASSIGNED NUMBERS*\n\n{num_list_text}"

    inline_buttons = []
    for n in numbers:
        phone = n['phone_number']
        inline_buttons.append([InlineKeyboardButton(text=f"📋 {phone}", callback_data=f"copy_{phone}")])
    
    inline_buttons.append([InlineKeyboardButton("🔄 Change Numbers", callback_data="act_change")])
    rew_link = db.get_setting("reward_group", "https://t.me")
    inline_buttons.append([InlineKeyboardButton("📨 View Reward Group", url=rew_link if rew_link.startswith("http") else "https://t.me")])

    reply_markup = InlineKeyboardMarkup(inline_buttons)
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if data.startswith("copy_"):
        await query.answer(f"Copied: {data.replace('copy_', '')}", show_alert=False)
        return

    if data.startswith("w_app_") or data.startswith("w_rej_"):
        if user_id not in config.ADMIN_IDS:
            await query.answer("Unauthorized", show_alert=True)
            return
        
        action, w_id = data.split("_")[1], int(data.split("_")[2])
        status = "approved" if action == "app" else "rejected"
        res = db.process_withdrawal(w_id, status)
        
        if res:
            await query.edit_message_text(f"✅ Withdrawal #{w_id} has been *{status.upper()}*.", parse_mode="Markdown")
            try:
                await context.bot.send_message(
                    chat_id=res['user_id'],
                    text=f"💸 Your withdrawal of `${res['amount']:.2f}` has been *{status.upper()}* by Admin.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            await query.answer("Withdrawal already processed or invalid.", show_alert=True)
        return

    await query.answer()

    if data.startswith("svc_"):
        svc = data.replace("svc_", "")
        assigned = db.assign_numbers(user_id, service=svc, count=3)
        await display_assigned_numbers(update, context, assigned)
    elif data == "act_change":
        assigned = db.assign_numbers(user_id, service="whatsapp", count=3)
        await display_assigned_numbers(update, context, assigned)

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
            await context.bot.send_message(chat_id=credited_user_id, text=notify_msg, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Failed to notify user {credited_user_id}: {e}")

# --- MAIN ENGINE ---

def  
