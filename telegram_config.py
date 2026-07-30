"""
telegram_config.py
-------------------
LOCAL-ONLY fallback for Telegram bot credentials.

If you're running this script on GitHub Actions (see
.github/workflows/earnings.yml), you don't need this file at all —
credentials there come from GitHub repo Secrets (TELEGRAM_BOT_TOKEN /
TELEGRAM_CHAT_ID), injected as environment variables. This file is only
read when those environment variables are NOT set, i.e. when you're
running india_earnings_dashboard.py directly on your own machine.

This file is listed in .gitignore, so it will not be pushed to GitHub —
keep your real token/chat ID here for local testing without worrying
about committing secrets by accident.

HOW TO GET A BOT TOKEN:
  1. Open Telegram, message @BotFather.
  2. Send /newbot and follow the prompts (choose a name + username).
  3. BotFather replies with a token that looks like:
     123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  4. Paste it into TELEGRAM_BOT_TOKEN below.

HOW TO GET YOUR CHAT ID:
  1. Send any message to your new bot (or add it to a group/channel and
     send a message there).
  2. In a browser, visit:
     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
  3. Look for "chat":{"id": ...} in the JSON response — that number
     (it will be negative for groups/channels) is your chat ID.
  4. Paste it into TELEGRAM_CHAT_ID below (as a string is fine).
"""

# --- Fill these in ---------------------------------------------------
TELEGRAM_BOT_TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "PUT_YOUR_CHAT_ID_HERE"

# --- Behaviour ---------------------------------------------------------
# Set to False any time you want to turn off Telegram alerts without
# deleting the credentials above.
TELEGRAM_ENABLED = True

# Which markets to include in the alert: "IN", "US", or "BOTH"
TELEGRAM_MARKETS = "BOTH"
