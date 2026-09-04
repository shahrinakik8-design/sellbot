import os
import logging
import sqlite3
import time
from datetime import datetime

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
PRIVATE_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "bot.db")
PAYMENT_INSTRUCTIONS = os.getenv(
    "PAYMENT_INSTRUCTIONS",
    "bKash / Nagad Personal: 01990491059 \n টাকা পাঠানোর পর Transaction ID পাঠান।",
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DIVIDER = "━━━━━━━━━━━━━━"

# Conversation states
(
    DEP_AMOUNT,
    DEP_TRXID,
    ADDPROD_NAME,
    ADDPROD_PRICE,
    ADDPROD_DESC,
    ADDPROD_FORWARD,
    BROADCAST_MSG,
) = range(7)

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            joined_at TEXT
        );

        CREATE TABLE IF NOT EXISTS products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,              -- 'apk' or 'method'
            name TEXT,
            price INTEGER,
            description TEXT,
            channel_msg_id INTEGER,     -- message id inside PRIVATE_CHANNEL_ID
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            price INTEGER,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS deposits (
            deposit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            trx_id TEXT,
            status TEXT DEFAULT 'pending',
            timestamp TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def ensure_user(user_id, username):
    if not get_user(user_id):
        conn = db()
        conn.execute(
            "INSERT INTO users (user_id, username, balance, joined_at) VALUES (?,?,0,?)",
            (user_id, username or "", datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()


def update_balance(user_id, delta):
    conn = db()
    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (delta, user_id))
    conn.commit()
    conn.close()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def is_banned(user_id):
    u = get_user(user_id)
    return bool(u and u["banned"])


def already_purchased(user_id, product_id):
    conn = db()
    row = conn.execute(
        "SELECT 1 FROM purchases WHERE user_id=? AND product_id=?", (user_id, product_id)
    ).fetchone()
    conn.close()
    return bool(row)


# ---------------------------------------------------------------------------
# KEYBOARDS
# ---------------------------------------------------------------------------
def main_menu_kb():
    return ReplyKeyboardMarkup(
        [
            ["💰 ডিপোজিট", "👛 ব্যালেন্স"],
            ["🛒 অ্যাপস শপ", "🎬 মেথড ভিডিও"],
            ["📦 আমার ক্রয়সমূহ"],
        ],
        resize_keyboard=True,
    )


def admin_menu_kb():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📱 Add APK Product", callback_data="adm_addprod_apk")],
            [InlineKeyboardButton("🎬 Add Method Video", callback_data="adm_addprod_method")],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
                InlineKeyboardButton("📊 Stats", callback_data="adm_stats"),
            ],
            [InlineKeyboardButton("👥 Users", callback_data="adm_users")],
        ]
    )


# ---------------------------------------------------------------------------
# BASIC USER HANDLERS
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username)
    if is_banned(user.id):
        await update.message.reply_text("🚫 আপনি ব্যান করা হয়েছে। অ্যাডমিনের সাথে যোগাযোগ করুন।")
        return
    await update.message.reply_html(
        f"✨ <b>স্বাগতম, {user.first_name}!</b> ✨\n{DIVIDER}\n"
        "🛍️ এখানে আপনি অ্যাপ কিনতে পারবেন এবং মেথড ভিডিও দেখতে পারবেন।\n"
        "নিচের মেনু থেকে অপশন বেছে নিন 👇",
        reply_markup=main_menu_kb(),
    )


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = get_user(user.id)
    bal = u["balance"] if u else 0
    await update.message.reply_html(f"👛 <b>আপনার ব্যালেন্স:</b> 💵 {bal} টাকা")


# ---------------------------------------------------------------------------
# DEPOSIT CONVERSATION
# ---------------------------------------------------------------------------
async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        f"💰 <b>ডিপোজিট করুন</b>\n{DIVIDER}\n{PAYMENT_INSTRUCTIONS}\n{DIVIDER}\n"
        "✅ পেমেন্ট করার পর, কত টাকা পাঠিয়েছেন লিখুন:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return DEP_AMOUNT


async def deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ শুধু সংখ্যায় টাকার পরিমাণ লিখুন।")
        return DEP_AMOUNT
    context.user_data["dep_amount"] = int(text)
    await update.message.reply_text("🧾 এখন Transaction ID (TrxID) পাঠান:")
    return DEP_TRXID


async def deposit_trxid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trx_id = update.message.text.strip()
    amount = context.user_data.get("dep_amount", 0)
    user = update.effective_user

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO deposits (user_id, amount, trx_id, status, timestamp) VALUES (?,?,?,?,?)",
        (user.id, amount, trx_id, "pending", datetime.utcnow().isoformat()),
    )
    deposit_id = cur.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_html(
        f"⏳ <b>ডিপোজিট রিকোয়েস্ট জমা হয়েছে!</b>\nঅ্যাডমিন যাচাই করে ব্যালেন্স যোগ করে দেবেন।",
        reply_markup=main_menu_kb(),
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"dep_approve_{deposit_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"dep_reject_{deposit_id}"),
            ]
        ]
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"📥 <b>নতুন ডিপোজিট রিকোয়েস্ট #{deposit_id}</b>\n{DIVIDER}\n"
                f"👤 User: <code>{user.id}</code> (@{user.username})\n"
                f"💵 Amount: {amount}\n🧾 TrxID: <code>{trx_id}</code>",
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning("Could not notify admin %s: %s", admin_id, e)

    return ConversationHandler.END


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❎ বাতিল করা হয়েছে।", reply_markup=main_menu_kb())
    return ConversationHandler.END


async def deposit_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("Only admin can do this.", show_alert=True)
        return

    action, deposit_id = query.data.rsplit("_", 1)
    deposit_id = int(deposit_id)

    conn = db()
    dep = conn.execute("SELECT * FROM deposits WHERE deposit_id=?", (deposit_id,)).fetchone()
    if not dep or dep["status"] != "pending":
        conn.close()
        await query.edit_message_text("⚠️ এই রিকোয়েস্ট আর পেন্ডিং নেই।")
        return

    if action == "dep_approve":
        conn.execute("UPDATE deposits SET status='approved' WHERE deposit_id=?", (deposit_id,))
        conn.commit()
        conn.close()
        update_balance(dep["user_id"], dep["amount"])
        await query.edit_message_text(f"✅ Deposit #{deposit_id} approved.")
        try:
            await context.bot.send_message(
                dep["user_id"],
                f"✅ <b>আপনার {dep['amount']} টাকার ডিপোজিট অনুমোদিত হয়েছে!</b> ব্যালেন্স যোগ হয়েছে 🎉",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        conn.execute("UPDATE deposits SET status='rejected' WHERE deposit_id=?", (deposit_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"❌ Deposit #{deposit_id} rejected.")
        try:
            await context.bot.send_message(
                dep["user_id"], f"❌ আপনার {dep['amount']} টাকার ডিপোজিট রিকোয়েস্ট বাতিল করা হয়েছে।"
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# LISTING (shop + method videos share the same product system)
# ---------------------------------------------------------------------------
async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    conn = db()
    products = conn.execute(
        "SELECT * FROM products WHERE category=? AND active=1", (category,)
    ).fetchall()
    conn.close()

    icon = "📱" if category == "apk" else "🎬"
    title = "অ্যাপস শপ" if category == "apk" else "মেথড ভিডিও"

    if not products:
        await update.message.reply_text(f"{icon} এই মুহূর্তে কোনো কিছু নেই।")
        return

    buttons = [
        [
            InlineKeyboardButton(
                f"{icon} {p['name']} — {'ফ্রি' if p['price'] == 0 else str(p['price']) + ' টাকা'}",
                callback_data=f"prod_{p['product_id']}",
            )
        ]
        for p in products
    ]
    await update.message.reply_html(
        f"{icon} <b>{title}</b>\n{DIVIDER}\nনিচ থেকে একটি বেছে নিন 👇",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_products(update, context, "apk")


async def method_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_products(update, context, "method")


async def product_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split("_")[1])
    conn = db()
    p = conn.execute("SELECT * FROM products WHERE product_id=?", (product_id,)).fetchone()
    conn.close()
    if not p:
        await query.edit_message_text("⚠️ পাওয়া যায়নি।")
        return

    owned = already_purchased(query.from_user.id, product_id)
    icon = "📱" if p["category"] == "apk" else "🎬"

    if owned or p["price"] == 0:
        btn_text = "▶️ ওপেন করুন / পান"
    else:
        btn_text = f"🔓 আনলক করুন ({p['price']} টাকা)"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text, callback_data=f"unlock_{product_id}")]])
    await query.edit_message_text(
        f"{icon} <b>{p['name']}</b>\n{DIVIDER}\n"
        f"💵 মূল্য: {'ফ্রি' if p['price'] == 0 else str(p['price']) + ' টাকা'}\n\n"
        f"{p['description'] or ''}",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


async def unlock_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    product_id = int(query.data.split("_")[1])

    conn = db()
    p = conn.execute("SELECT * FROM products WHERE product_id=?", (product_id,)).fetchone()
    u = conn.execute("SELECT * FROM users WHERE user_id=?", (user.id,)).fetchone()

    if not p:
        conn.close()
        await query.edit_message_text("⚠️ পাওয়া যায়নি।")
        return

    owned = already_purchased(user.id, product_id)

    if not owned and p["price"] > 0:
        if not u or u["balance"] < p["price"]:
            conn.close()
            await query.edit_message_text(
                f"❌ <b>ব্যালেন্স অপর্যাপ্ত!</b>\nমূল্য {p['price']} টাকা। আগে ডিপোজিট করুন 💰",
                parse_mode=ParseMode.HTML,
            )
            return
        conn.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (p["price"], user.id))
        conn.execute(
            "INSERT INTO purchases (user_id, product_id, price, timestamp) VALUES (?,?,?,?)",
            (user.id, product_id, p["price"], datetime.utcnow().isoformat()),
        )
        conn.commit()

    conn.close()

    await query.edit_message_text(f"✅ <b>পাঠানো হচ্ছে...</b> 🚀", parse_mode=ParseMode.HTML)

    if p["channel_msg_id"]:
        try:
            await context.bot.copy_message(
                chat_id=user.id,
                from_chat_id=PRIVATE_CHANNEL_ID,
                message_id=p["channel_msg_id"],
            )
        except Exception as e:
            logger.error("copy_message failed: %s", e)
            await context.bot.send_message(
                user.id, "⚠️ ফাইল পাঠাতে সমস্যা হয়েছে, অ্যাডমিনের সাথে যোগাযোগ করুন।"
            )
    else:
        await context.bot.send_message(user.id, "⚠️ কনটেন্ট পাওয়া যায়নি, অ্যাডমিনের সাথে যোগাযোগ করুন।")


async def my_purchases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = db()
    rows = conn.execute(
        """SELECT pr.name, pr.category, pu.price, pu.timestamp FROM purchases pu
           JOIN products pr ON pr.product_id = pu.product_id
           WHERE pu.user_id=? ORDER BY pu.id DESC""",
        (user.id,),
    ).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("📦 আপনার কোনো ক্রয় নেই।")
        return
    lines = []
    for r in rows:
        icon = "📱" if r["category"] == "apk" else "🎬"
        lines.append(f"{icon} {r['name']} — {r['price']} টাকা — {r['timestamp'][:10]}")
    await update.message.reply_html(f"📦 <b>আপনার ক্রয়সমূহ</b>\n{DIVIDER}\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# ADMIN PANEL
# ---------------------------------------------------------------------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_html(f"🛠 <b>Admin Panel</b>\n{DIVIDER}", reply_markup=admin_menu_kb())


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db()
    total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    total_revenue = conn.execute("SELECT COALESCE(SUM(price),0) s FROM purchases").fetchone()["s"]
    total_deposits = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM deposits WHERE status='approved'"
    ).fetchone()["s"]
    pending = conn.execute("SELECT COUNT(*) c FROM deposits WHERE status='pending'").fetchone()["c"]
    conn.close()
    await query.edit_message_text(
        f"📊 <b>Stats</b>\n{DIVIDER}\n👥 Users: {total_users}\n💵 Sales revenue: {total_revenue}\n"
        f"💰 Approved deposits: {total_deposits}\n⏳ Pending deposits: {pending}",
        reply_markup=admin_menu_kb(),
        parse_mode=ParseMode.HTML,
    )


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db()
    rows = conn.execute("SELECT * FROM users ORDER BY joined_at DESC LIMIT 30").fetchall()
    conn.close()
    text = f"👥 <b>সাম্প্রতিক ৩০ জন ইউজার</b>\n{DIVIDER}\n" + "\n".join(
        f"<code>{r['user_id']}</code> @{r['username']} — {r['balance']} টাকা {'🚫' if r['banned'] else ''}"
        for r in rows
    )
    await query.edit_message_text(text[:4000], reply_markup=admin_menu_kb(), parse_mode=ParseMode.HTML)


async def addbalance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addbalance <user_id> <amount>")
        return
    ensure_user(target_id, "")
    update_balance(target_id, amount)
    await update.message.reply_text(f"✅ {target_id} কে {amount} টাকা যোগ করা হয়েছে।")
    try:
        await context.bot.send_message(target_id, f"💰 আপনার একাউন্টে {amount} টাকা যোগ করা হয়েছে।")
    except Exception:
        pass


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        target_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    conn = db()
    conn.execute("UPDATE users SET banned=1 WHERE user_id=?", (target_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"🚫 {target_id} ব্যান করা হয়েছে।")


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        target_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    conn = db()
    conn.execute("UPDATE users SET banned=0 WHERE user_id=?", (target_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ {target_id} আনব্যান করা হয়েছে।")


# --- Add product conversation (delivers via forwarded channel post) ---
async def addprod_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return ConversationHandler.END
    category = "apk" if query.data == "adm_addprod_apk" else "method"
    context.user_data["p_category"] = category
    icon = "📱" if category == "apk" else "🎬"
    await query.edit_message_text(f"{icon} প্রোডাক্টের নাম লিখুন:")
    return ADDPROD_NAME


async def addprod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("💵 মূল্য লিখুন (ফ্রি হলে 0 লিখুন):")
    return ADDPROD_PRICE


async def addprod_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ সংখ্যায় লিখুন:")
        return ADDPROD_PRICE
    context.user_data["p_price"] = int(text)
    await update.message.reply_text("📝 বিবরণ লিখুন (না থাকলে - লিখুন):")
    return ADDPROD_DESC


async def addprod_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_desc"] = update.message.text.strip()
    await update.message.reply_html(
        f"📤 এখন প্রাইভেট চ্যানেল থেকে সংশ্লিষ্ট পোস্টটি (APK/ভিডিও) এই চ্যাটে <b>ফরওয়ার্ড</b> করুন।\n"
        f"(কপি-পেস্ট নয়, সরাসরি Forward করতে হবে)"
    )
    return ADDPROD_FORWARD


def extract_forward_origin(message):
    """Works with both new (forward_origin) and legacy (forward_from_chat) PTB/Bot API fields."""
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None)
        msg_id = getattr(origin, "message_id", None)
        if chat and msg_id:
            return chat.id, msg_id
    chat = getattr(message, "forward_from_chat", None)
    msg_id = getattr(message, "forward_from_message_id", None)
    if chat and msg_id:
        return chat.id, msg_id
    return None, None


async def addprod_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, msg_id = extract_forward_origin(update.message)
    if not chat_id or chat_id != PRIVATE_CHANNEL_ID:
        await update.message.reply_text(
            "⚠️ এটা কনফিগার করা প্রাইভেট চ্যানেলের পোস্ট মনে হচ্ছে না। সঠিক চ্যানেল থেকে Forward করুন।"
        )
        return ADDPROD_FORWARD

    conn = db()
    conn.execute(
        """INSERT INTO products (category, name, price, description, channel_msg_id, active)
           VALUES (?,?,?,?,?,1)""",
        (
            context.user_data["p_category"],
            context.user_data["p_name"],
            context.user_data["p_price"],
            context.user_data["p_desc"],
            msg_id,
        ),
    )
    conn.commit()
    conn.close()
    await update.message.reply_html(
        f"✅ <b>প্রোডাক্ট যোগ করা হয়েছে!</b> 🎉", reply_markup=main_menu_kb()
    )
    return ConversationHandler.END


# --- Broadcast conversation ---
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return ConversationHandler.END
    await query.edit_message_text("📢 যে মেসেজটি সব ইউজারকে পাঠাতে চান তা লিখুন:")
    return BROADCAST_MSG


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    conn = db()
    users = conn.execute("SELECT user_id FROM users WHERE banned=0").fetchall()
    conn.close()

    sent, failed = 0, 0
    status_msg = await update.message.reply_text("📤 পাঠানো হচ্ছে...")
    for u in users:
        try:
            await context.bot.send_message(u["user_id"], text)
            sent += 1
        except Exception:
            failed += 1
    await status_msg.edit_text(f"✅ Broadcast শেষ।\n✔️ Sent: {sent}\n❌ Failed: {failed}")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN missing in .env")

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Basic
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^👛 ব্যালেন্স$"), balance_cmd))
    app.add_handler(MessageHandler(filters.Regex("^🛒 অ্যাপস শপ$"), shop))
    app.add_handler(MessageHandler(filters.Regex("^🎬 মেথড ভিডিও$"), method_videos))
    app.add_handler(MessageHandler(filters.Regex("^📦 আমার ক্রয়সমূহ$"), my_purchases))

    # Deposit conversation
    deposit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💰 ডিপোজিট$"), deposit_start)],
        states={
            DEP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount)],
            DEP_TRXID: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_trxid)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    app.add_handler(deposit_conv)

    app.add_handler(CallbackQueryHandler(deposit_decision, pattern="^dep_(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(product_detail, pattern="^prod_"))
    app.add_handler(CallbackQueryHandler(unlock_product, pattern="^unlock_"))

    # Admin
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("addbalance", addbalance_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^adm_stats$"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern="^adm_users$"))

    addprod_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(addprod_start, pattern="^adm_addprod_(apk|method)$")
        ],
        states={
            ADDPROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addprod_name)],
            ADDPROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addprod_price)],
            ADDPROD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, addprod_desc)],
            ADDPROD_FORWARD: [MessageHandler(filters.ALL & ~filters.COMMAND, addprod_forward)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    app.add_handler(addprod_conv)

    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_start, pattern="^adm_broadcast$")],
        states={
            BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    app.add_handler(broadcast_conv)

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
