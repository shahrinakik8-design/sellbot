# Telegram Digital Shop Bot

## Feature list
- 🎨 Colorful, emoji-rich UI with bottom persistent buttons + inline menus
- 💰 Deposit (manual bKash/Nagad — admin approves via inline Approve/Reject buttons)
- 📱 APK products — stored as posts in your private channel, delivered
  **automatically** to the buyer via Telegram's `copy_message` (no manual upload needed per sale)
- 🎬 Method videos — same system, forwarded straight from the private channel
  when a user unlocks/opens them (free or paid, your choice per item)
- 🛠 Full admin panel: broadcast, add product, deposit approve/reject,
  add balance, ban/unban, stats, user list

## ⚠️ Your credentials are already filled in `.env`
```
BOT_TOKEN=8898786459:AAGcFGNFSD82lRnibnYqkjZxLLlwYDmuVtA
ADMIN_IDS=1586853120
PRIVATE_CHANNEL_ID=-1003892355441
```
Keep this file private — anyone with the token can control your bot. Don't
commit `.env` to a public repo (a `.gitignore` covering it is recommended).

## Setup

1. Python 3.10+ lagbe.
2. Dependencies install koro:
   ```
   pip install -r requirements.txt
   ```
3. Run koro:
   ```
   python bot.py
   ```
4. **Bot-কে private channel এ Admin বানাও** (`-1003892355441`). Bot member/admin
   না থাকলে সেখান থেকে `copy_message` দিয়ে কনটেন্ট ফরওয়ার্ড করতে পারবে না।

## Admin commands
- `/admin` — admin panel (inline buttons: Add APK, Add Method Video, Broadcast, Stats, Users)
- `/addbalance <user_id> <amount>` — manual balance add
- `/ban <user_id>` / `/unban <user_id>`

## কিভাবে নতুন APK / Method Video যোগ করবেন
এখন ফাইল বট-এ আলাদা করে আপলোড করতে হয় না — সরাসরি চ্যানেলের পোস্ট থেকে
কাজ করে:

1. আগে সেই APK ফাইল বা মেথড ভিডিওটা তোমার প্রাইভেট চ্যানেলে (`-1003892355441`)
   পোস্ট করো (caption সহ বা ছাড়া, যেকোনোভাবে)।
2. বটে `/admin` → **📱 Add APK Product** অথবা **🎬 Add Method Video** চাপো।
3. নাম দাও → মূল্য দাও (ফ্রি হলে `0`) → বিবরণ দাও।
4. এরপর ধাপে, চ্যানেলে যাওয়া সেই পোস্টটা **Forward** করে বটের চ্যাটে পাঠাও
   (কপি-পেস্ট নয়, আসল Forward বাটন দিয়ে)।
5. ব্যাস — প্রোডাক্ট সেভ হয়ে গেছে।

## User flow
- **🛒 অ্যাপস শপ** — APK প্রোডাক্ট লিস্ট দেখায় → ক্লিক করলে detail + "🔓 আনলক করুন" বাটন
  → ব্যালেন্স যথেষ্ট থাকলে টাকা কেটে সাথে সাথে bot চ্যানেল থেকে ফাইলটা
  `copy_message` দিয়ে ফরওয়ার্ড করে দেয়।
- **🎬 মেথড ভিডিও** — একই সিস্টেম, আলাদা ক্যাটাগরি। মূল্য `0` দিলে সবার জন্য ফ্রি
  (unlock চাপলেই সাথে সাথে ভিডিও পাঠিয়ে দেবে), মূল্য দিলে balance থেকে কাটবে।
- একবার কেনা/আনলক করা প্রোডাক্ট আবার চাইলে টাকা না কেটেই পুনরায় পাঠিয়ে দেয়
  (already-purchased check করা আছে)।

## Notes
- Database হিসেবে SQLite (`bot.db`) — ছোট/মাঝারি স্কেলের জন্য যথেষ্ট।
- Bot ke 24/7 চালু রাখতে VPS-এ `systemd` / `tmux` / `screen` / PM2 দিয়ে
  background এ চালাও।
- `copy_message` কাজ করার জন্য bot অবশ্যই ওই channel এর member/admin হতে হবে।
