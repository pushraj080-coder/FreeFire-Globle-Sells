# telegram_market_bot.py
import logging
import os
import json
import uuid
from functools import wraps
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    KeyboardButton, InputMediaPhoto, ParseMode
)
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler,
    ConversationHandler, CallbackContext
)

# ========== CONFIG ==========
TOKEN = "8196162228:AAE2FYJXtHOMOuzPNm5nM6ZrraDF5ZJuRpU"
ADMIN_CHAT_ID = 8044436359  # replace with your admin chat id (int)

BASE_COLLECTION_DIR = "collections"  # structure: collections/{country_key}/{budget_key}/
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PENDING_TX_FILE = os.path.join(DATA_DIR, "pending_transactions.json")
PENDING_SALES_FILE = os.path.join(DATA_DIR, "pending_sales.json")

# Razorpay payment link (as user requested)
PAYMENT_LINK = "https://razorpay.me/@payoutseen"

# Countries & budgets mapping (keys used in folder names)
COUNTRIES = [
    ("india", "India"),
    ("brazil", "Brazil"),
    ("indonesia", "Indonesia"),
    ("thailand", "Thailand"),
    ("mexico", "Mexico"),
    ("vietnam", "Vietnam"),
    ("singapore", "Singapore"),
    ("bangladesh", "Bangladesh"),
    ("nepal", "Nepal"),
]

BUDGETS = [
    ("10000", "Rs 10000"),
    ("12000", "Rs 12000"),
    ("150000", "Rs 150000"),
    ("20000", "Rs 20000"),
    ("25000", "Rs 25000"),
    ("30000", "Rs 30000"),
    ("50000", "Rs 50000"),
]

# ========== Logging ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== Helpers for persistent simple storage ==========
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# initialize files
save_json(PENDING_TX_FILE, load_json(PENDING_TX_FILE))
save_json(PENDING_SALES_FILE, load_json(PENDING_SALES_FILE))

# ========== Decorator to restrict admin-only handlers ==========
def admin_only(func):
    @wraps(func)
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_CHAT_ID:
            update.message.reply_text("This command is for admin only.")
            return
        return func(update, context, *args, **kwargs)
    return wrapped

# ========== Conversation states ==========
(
    START,
    COUNTRY_SELECT,
    BUY_SELL_SELECT,
    BUY_BUDGET_SELECT,
    SHOW_COLLECTION,
    AWAIT_REFERRAL,
    AWAIT_PAYMENT_PROOF,
    SELL_COUNTRY_SELECT,
    SELL_UID_LEVEL,
    SELL_COLLECTION_UPLOAD,
    WAITING_ADMIN_PRICE,
    SELL_CHOOSE_CONTACT,
    AWAIT_CONTACT_DETAILS,
) = range(13)

# ========== Start handler ==========
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    keyboard = []
    for i, (_, display) in enumerate(COUNTRIES, start=1):
        keyboard.append([InlineKeyboardButton(f"{i}. {display}", callback_data=f"country_{COUNTRIES[i-1][0]}")])
    reply = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        f"Hello {user.first_name}! Select country:",
        reply_markup=reply
    )
    return COUNTRY_SELECT

# ========== Country selection callback (shared for buy/sell start) ==========
def country_selected_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data  # e.g. country_india
    country_key = data.split("_", 1)[1]
    context.user_data['selected_country'] = country_key

    # Offer Buy or Sell
    keyboard = [
        [InlineKeyboardButton("FreeFire IDs Buy", callback_data="action_buy")],
        [InlineKeyboardButton("FreeFire IDs Sell", callback_data="action_sell")],
    ]
    query.edit_message_text(f"You selected *{country_key.title()}*. Choose:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return BUY_SELL_SELECT

# ========== Buy flow: budgets ==========
def buy_sell_choice_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    action = query.data  # action_buy or action_sell
    if action == "action_buy":
        # show budgets
        buttons = []
        for key, label in BUDGETS:
            buttons.append([InlineKeyboardButton(label, callback_data=f"budget_{key}")])
        query.edit_message_text("Select your budget:", reply_markup=InlineKeyboardMarkup(buttons))
        return BUY_BUDGET_SELECT
    else:
        # Sell flow: ask country again (we already have country) but proceed to ask UID+Level
        query.edit_message_text("Please enter UID and Level in format: UID LEVEL\nExample: 12345678 72")
        return SELL_UID_LEVEL

# ========== When budget selected: send collection files ==========
def budget_selected_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    budget_key = query.data.split("_",1)[1]
    country_key = context.user_data.get('selected_country')
    context.user_data['selected_budget'] = budget_key

    # locate collection folder
    folder = os.path.join(BASE_COLLECTION_DIR, country_key, budget_key)
    if not os.path.exists(folder):
        query.edit_message_text("Sorry, no items available for that budget right now.")
        return ConversationHandler.END

    # List files and send as media group if images, else send individually with 'Buy Now' button
    files = sorted(os.listdir(folder))
    if not files:
        query.edit_message_text("No items found in collection folder.")
        return ConversationHandler.END

    # We'll send each file with a caption and a Buy Now button
    for fname in files:
        file_path = os.path.join(folder, fname)
        caption = f"{fname}\n\nClick Buy Now to purchase this ID."
        buy_button = InlineKeyboardMarkup([[InlineKeyboardButton("Buy Now", callback_data=f"buynow|{country_key}|{budget_key}|{fname}")]])
        try:
            if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                query.message.reply_photo(open(file_path, "rb"), caption=caption, reply_markup=buy_button)
            elif fname.lower().endswith((".mp4", ".mov", ".3gp")):
                query.message.reply_video(open(file_path, "rb"), caption=caption, reply_markup=buy_button)
            else:
                query.message.reply_document(open(file_path, "rb"), caption=caption, reply_markup=buy_button)
        except Exception as e:
            logger.exception("Error sending file: %s", e)
            query.message.reply_text(f"Could not send file {fname}.")
    query.edit_message_text("All items sent. Tap Buy Now on any item to proceed.")
    return SHOW_COLLECTION

# ========== When user taps Buy Now ==========
def buynow_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    payload = query.data.split("|")  # buynow|country|budget|filename
    _, country_key, budget_key, fname = payload
    context.user_data['pending_buy'] = {
        "country": country_key,
        "budget": budget_key,
        "filename": fname
    }
    # Ask referral code or No
    keyboard = [
        [InlineKeyboardButton("No", callback_data="ref_no")],
        [InlineKeyboardButton("I have referral - Paste code", callback_data="ref_paste")],
    ]
    query.message.reply_text("If you came through someone's referral, paste their code below or press No.", reply_markup=InlineKeyboardMarkup(keyboard))
    return AWAIT_REFERRAL

def referral_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.data == "ref_no":
        context.user_data['referral'] = None
        # send payment link
        text = f"Pay here: {PAYMENT_LINK}\n\nAfter payment, click Done (Paid) button below and then upload payment proof (screenshot)."
        keyboard = [[InlineKeyboardButton("Done, Paid", callback_data="paid_done")]]
        query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAIT_PAYMENT_PROOF
    else:
        # We'll ask user to paste code as a text message
        query.message.reply_text("Please paste the referral code as a message now.")
        return AWAIT_REFERRAL

# When user sends referral code as text
def received_referral_text(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    context.user_data['referral'] = text
    update.message.reply_text(f"Referral noted: {text}\nNow please pay using this link:\n{PAYMENT_LINK}\nAfter payment press Done (Paid).")
    keyboard = [[InlineKeyboardButton("Done, Paid", callback_data="paid_done")]]
    update.message.reply_text("Click below after paying:", reply_markup=InlineKeyboardMarkup(keyboard))
    return AWAIT_PAYMENT_PROOF

# Paid done -> ask for payment proof upload
def paid_done_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user = update.effective_user
    # create a pending transaction entry
    tx_id = str(uuid.uuid4())
    pending = load_json(PENDING_TX_FILE)
    pending[tx_id] = {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "pending_buy": context.user_data.get('pending_buy'),
        "referral": context.user_data.get('referral'),
        "status": "waiting_proof"
    }
    save_json(PENDING_TX_FILE, pending)
    query.message.reply_text("Please upload payment proof (screenshot/photo). Once uploaded it will be sent to admin for approval.")
    return AWAIT_PAYMENT_PROOF

# When user uploads photo as payment proof
def payment_proof_handler(update: Update, context: CallbackContext):
    # accept photo or document
    user = update.effective_user
    photos = update.message.photo
    doc = update.message.document
    pending = load_json(PENDING_TX_FILE)

    # find user's "waiting_proof" tx
    tx_id = None
    for tid, info in pending.items():
        if info.get("user_id") == user.id and info.get("status") == "waiting_proof":
            tx_id = tid
            break

    if not tx_id:
        update.message.reply_text("No pending payment found. Start buying again with /start.")
        return ConversationHandler.END

    # forward the file to admin with approve/reject buttons
    caption = f"Payment proof from @{user.username or user.first_name}\nTX ID: {tx_id}\nUserID: {user.id}"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Approve", callback_data=f"admin_approve|{tx_id}"),
            InlineKeyboardButton("Reject", callback_data=f"admin_reject|{tx_id}")
        ]
    ])

    if photos:
        # take highest res
        f = photos[-1].get_file()
        # send to admin as photo
        context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=f.file_id, caption=caption, reply_markup=keyboard)
    elif doc:
        f = doc.get_file()
        context.bot.send_document(chat_id=ADMIN_CHAT_ID, document=f.file_id, caption=caption, reply_markup=keyboard)
    else:
        update.message.reply_text("Please send a photo or document as proof.")
        return AWAIT_PAYMENT_PROOF

    # update pending to 'await_admin'
    pending[tx_id]['status'] = 'awaiting_admin'
    save_json(PENDING_TX_FILE, pending)
    update.message.reply_text("Payment proof sent to admin. You'll be notified after approval.")
    return ConversationHandler.END

# Admin approve/reject callbacks for buys
def admin_approve_reject_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data  # admin_approve|txid or admin_reject|txid
    action, tx_id = data.split("|", 1)
    pending = load_json(PENDING_TX_FILE)
    tx = pending.get(tx_id)
    if not tx:
        query.edit_message_caption("Transaction not found or already processed.")
        return

    user_id = tx['user_id']
    if action == "admin_approve":
        # mark approved
        tx['status'] = 'approved'
        save_json(PENDING_TX_FILE, pending)
        # notify user - as requested English message about technical issue and 48hrs
        context.bot.send_message(chat_id=user_id, text=(
            "Thank you for your payment. Our system encountered a technical issue.\n"
            "Your payment will be received and processed within 48 hours. Please wait until then.\n"
            "Thank you for joining us."
        ))
        query.edit_message_caption(f"{query.message.caption}\n\n✅ Approved by admin.")
    else:
        tx['status'] = 'rejected'
        save_json(PENDING_TX_FILE, pending)
        context.bot.send_message(chat_id=user_id, text="Your payment was rejected by admin. Contact support.")
        query.edit_message_caption(f"{query.message.caption}\n\n❌ Rejected by admin.")

# ========== SELL Flow Handlers ==========
def sell_uid_level_handler(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    # expecting format: UID LEVEL
    parts = text.split()
    if len(parts) < 2:
        update.message.reply_text("Please enter in format: UID LEVEL\nExample: 12345678 72")
        return SELL_UID_LEVEL
    uid = parts[0]
    level = parts[1]
    context.user_data['sell_uid'] = uid
    context.user_data['sell_level'] = level
    update.message.reply_text("Now upload photos/videos of the ID (ownership proof). Send all files and then send /done when finished.")
    # prepare a sale entry in memory
    sale_id = str(uuid.uuid4())
    context.user_data['sale_id'] = sale_id
    pending_sales = load_json(PENDING_SALES_FILE)
    pending_sales[sale_id] = {
        "user_id": update.effective_user.id,
        "username": update.effective_user.username,
        "uid": uid,
        "level": level,
        "media": [],
        "status": "waiting_media"
    }
    save_json(PENDING_SALES_FILE, pending_sales)
    return SELL_COLLECTION_UPLOAD

def sell_media_handler(update: Update, context: CallbackContext):
    # accept photo/video/document and save file_id
    sale_id = context.user_data.get('sale_id')
    if not sale_id:
        update.message.reply_text("No sale in progress. Start with /start.")
        return ConversationHandler.END

    pending_sales = load_json(PENDING_SALES_FILE)
    sale = pending_sales.get(sale_id)
    if not sale:
        update.message.reply_text("Sale not found. Start again.")
        return ConversationHandler.END

    saved = None
    if update.message.photo:
        f = update.message.photo[-1].get_file()
        saved = {"type": "photo", "file_id": f.file_id}
    elif update.message.video:
        f = update.message.video.get_file()
        saved = {"type": "video", "file_id": f.file_id}
    elif update.message.document:
        f = update.message.document.get_file()
        saved = {"type": "document", "file_id": f.file_id}
    else:
        update.message.reply_text("Send photo/video/document as proof.")
        return SELL_COLLECTION_UPLOAD

    sale['media'].append(saved)
    pending_sales[sale_id] = sale
    save_json(PENDING_SALES_FILE, pending_sales)
    update.message.reply_text("Media received. Send more or send /done when finished.")
    return SELL_COLLECTION_UPLOAD

def sell_done_handler(update: Update, context: CallbackContext):
    sale_id = context.user_data.get('sale_id')
    if not sale_id:
        update.message.reply_text("No sale found. Start again with /start.")
        return ConversationHandler.END

    pending_sales = load_json(PENDING_SALES_FILE)
    sale = pending_sales.get(sale_id)
    if not sale:
        update.message.reply_text("Sale not found.")
        return ConversationHandler.END

    # forward all media to admin with Add Price button
    caption = (f"New SELL submission by @{sale.get('username')}\n"
               f"Sale ID: {sale_id}\nUID: {sale.get('uid')} Level: {sale.get('level')}")
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Add Price", callback_data=f"admin_addprice|{sale_id}")]])
    # send first media with caption and buttons, others as media
    if sale['media']:
        first = sale['media'][0]
        if first['type'] == 'photo':
            context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=first['file_id'], caption=caption, reply_markup=keyboard)
        elif first['type'] == 'video':
            context.bot.send_video(chat_id=ADMIN_CHAT_ID, video=first['file_id'], caption=caption, reply_markup=keyboard)
        else:
            context.bot.send_document(chat_id=ADMIN_CHAT_ID, document=first['file_id'], caption=caption, reply_markup=keyboard)
        for m in sale['media'][1:]:
            if m['type'] == 'photo':
                context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=m['file_id'])
            elif m['type'] == 'video':
                context.bot.send_video(chat_id=ADMIN_CHAT_ID, video=m['file_id'])
            else:
                context.bot.send_document(chat_id=ADMIN_CHAT_ID, document=m['file_id'])
    else:
        context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption, reply_markup=keyboard)

    sale['status'] = 'sent_to_admin'
    pending_sales[sale_id] = sale
    save_json(PENDING_SALES_FILE, pending_sales)
    update.message.reply_text("Your collection has been submitted. Admin will set a price and you'll be notified.")
    return ConversationHandler.END

# Admin clicks Add Price -> bot asks admin to reply with price
def admin_addprice_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    _, sale_id = query.data.split("|",1)
    # ask admin to reply with price using reply_to_message
    context.user_data['setting_price_sale'] = sale_id
    query.message.reply_text(f"Admin: Reply to this message with the price for sale id {sale_id} in plain text (e.g., Rs 1500).")
    return WAITING_ADMIN_PRICE

def admin_set_price_reply(update: Update, context: CallbackContext):
    # only admin should do this
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        update.message.reply_text("Only admin can set price here.")
        return

    # we expect that admin replies to the bot's prompt; we instead check context.user_data if sale id stored
    sale_id = context.user_data.get('setting_price_sale')
    if not sale_id:
        update.message.reply_text("No sale_id in context. Use Add Price button to start.")
        return

    price_text = update.message.text.strip()
    pending_sales = load_json(PENDING_SALES_FILE)
    sale = pending_sales.get(sale_id)
    if not sale:
        update.message.reply_text("Sale not found.")
        return

    sale['price'] = price_text
    sale['status'] = 'price_set'
    pending_sales[sale_id] = sale
    save_json(PENDING_SALES_FILE, pending_sales)

    # notify seller with price and options to accept (Deal Done)
    seller_id = sale['user_id']
    keyboard = [
        [InlineKeyboardButton("Deal Done (Accept Price)", callback_data=f"seller_accept|{sale_id}")],
        [InlineKeyboardButton("Cancel", callback_data=f"seller_cancel|{sale_id}")]
    ]
    context.bot.send_message(chat_id=seller_id, text=f"Admin set the price for your ID: {price_text}\nDo you accept?", reply_markup=InlineKeyboardMarkup(keyboard))
    update.message.reply_text("Price set and seller notified.")
    # clear context
    context.user_data.pop('setting_price_sale', None)
    return ConversationHandler.END

# Seller accepts -> bot shows contact options (Gmail or Facebook). We DO NOT ask for passwords.
def seller_accept_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    _, sale_id = query.data.split("|",1)
    keyboard = [
        [InlineKeyboardButton("Provide Gmail (email) only", callback_data=f"contact_gmail|{sale_id}")],
        [InlineKeyboardButton("Provide Facebook profile link", callback_data=f"contact_fb|{sale_id}")]
    ]
    query.message.reply_text("Which contact method will you share? (DO NOT share passwords. Only share email or profile link.)", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELL_CHOOSE_CONTACT

def seller_contact_choice_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    method, sale_id = data.split("|",1)
    context.user_data['current_sale_contact'] = {'sale_id': sale_id, 'method': method}
    if method == "contact_gmail":
        query.message.reply_text("Please type your Gmail address (only email, no password). Also include any additional notes (like backup email).")
    else:
        query.message.reply_text("Please paste your Facebook profile link (no password). Also include any additional notes.")
    return AWAIT_CONTACT_DETAILS

def seller_contact_received(update: Update, context: CallbackContext):
    info = context.user_data.get('current_sale_contact')
    if not info:
        update.message.reply_text("No contact flow in progress.")
        return ConversationHandler.END
    sale_id = info['sale_id']
    method = info['method']
    text = update.message.text.strip()

    pending_sales = load_json(PENDING_SALES_FILE)
    sale = pending_sales.get(sale_id)
    if not sale:
        update.message.reply_text("Sale not found.")
        return ConversationHandler.END

    sale['buyer_contact_method'] = method
    sale['buyer_contact_details'] = text
    sale['status'] = 'contact_provided'
    pending_sales[sale_id] = sale
    save_json(PENDING_SALES_FILE, pending_sales)

    # forward details to admin
    admin_text = (f"Seller provided contact for Sale ID {sale_id}\nUID: {sale['uid']} Level: {sale['level']}\n"
                  f"Contact method: {method}\nDetails: {text}\nSeller: @{sale.get('username')}")
    context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text)
    update.message.reply_text("Contact details forwarded to admin. Admin will confirm and finalize the deal.")
    return ConversationHandler.END

# Seller cancel
def seller_cancel_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    _, sale_id = query.data.split("|",1)
    pending_sales = load_json(PENDING_SALES_FILE)
    sale = pending_sales.get(sale_id)
    if sale:
        sale['status'] = 'cancelled'
        pending_sales[sale_id] = sale
        save_json(PENDING_SALES_FILE, pending_sales)
    query.edit_message_text("Sale cancelled.")
    return ConversationHandler.END

# ========== Misc / fallback handlers ==========
def unknown(update: Update, context: CallbackContext):
    update.message.reply_text("Command not recognized. Use /start to begin.")

def error_handler(update: Update, context: CallbackContext):
    logger.exception("Update caused error: %s", context.error)

# ========== Build dispatcher & handlers ==========
def main():
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    # start conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            COUNTRY_SELECT: [
                CallbackQueryHandler(country_selected_callback, pattern=r'^country_')
            ],
            BUY_SELL_SELECT: [
                CallbackQueryHandler(buy_sell_choice_callback, pattern=r'^action_')
            ],
            BUY_BUDGET_SELECT: [
                CallbackQueryHandler(budget_selected_callback, pattern=r'^budget_')
            ],
            SHOW_COLLECTION: [
                CallbackQueryHandler(buynow_callback, pattern=r'^buynow\|')
            ],
            AWAIT_REFERRAL: [
                CallbackQueryHandler(referral_callback, pattern=r'^ref_'),
                MessageHandler(Filters.text & ~Filters.command, received_referral_text)
            ],
            AWAIT_PAYMENT_PROOF: [
                CallbackQueryHandler(paid_done_callback, pattern=r'^paid_done$'),
                MessageHandler(Filters.photo | Filters.document, payment_proof_handler)
            ],
            SELL_UID_LEVEL: [
                MessageHandler(Filters.text & ~Filters.command, sell_uid_level_handler)
            ],
            SELL_COLLECTION_UPLOAD: [
                MessageHandler((Filters.photo | Filters.video | Filters.document) & ~Filters.command, sell_media_handler),
                CommandHandler('done', sell_done_handler)
            ],
            SELL_CHOOSE_CONTACT: [
                CallbackQueryHandler(seller_contact_choice_callback, pattern=r'^contact_')
            ],
            AWAIT_CONTACT_DETAILS: [
                MessageHandler(Filters.text & ~Filters.command, seller_contact_received)
            ],
            WAITING_ADMIN_PRICE: [
                MessageHandler(Filters.text & Filters.user(user_id=ADMIN_CHAT_ID), admin_set_price_reply)
            ],
        },
        fallbacks=[MessageHandler(Filters.command, unknown)],
        allow_reentry=True,
        per_user=True
    )

    dp.add_handler(conv_handler)

    # admin callbacks (approve/reject/addprice)
    dp.add_handler(CallbackQueryHandler(admin_approve_reject_callback, pattern=r'^admin_(approve|reject)\|'))
    dp.add_handler(CallbackQueryHandler(admin_addprice_callback, pattern=r'^admin_addprice\|'))
    dp.add_handler(CallbackQueryHandler(seller_accept_callback, pattern=r'^seller_accept\|'))
    dp.add_handler(CallbackQueryHandler(seller_cancel_callback, pattern=r'^seller_cancel\|'))
    dp.add_handler(CallbackQueryHandler(seller_contact_choice_callback, pattern=r'^contact_'))
    # other callbacks (buynow referral etc.)
    dp.add_handler(CallbackQueryHandler(buynow_callback, pattern=r'^buynow\|'))
    dp.add_handler(CallbackQueryHandler(referral_callback, pattern=r'^ref_'))
    dp.add_handler(CallbackQueryHandler(paid_done_callback, pattern=r'^paid_done$'))

    dp.add_error_handler(error_handler)

    logger.info("Starting bot...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
