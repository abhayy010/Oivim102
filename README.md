# SellerSmart Support Bot — Render Web Service v6

1. Upload these files to the ROOT of your GitHub repository.
2. Create a new **Web Service** in Render from that repository (not Background Worker).
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python sellersmart.py`
5. Environment variables: `BOT_TOKEN` = your current BotFather token; `PYTHON_VERSION` = `3.11.11`.
6. Health Check Path: `/health` (also set in render.yaml).

The bot uses Telegram long polling and starts a small HTTP health endpoint on Render's `PORT` so it can run as a Web Service. Do not run another copy of this bot with the same token at the same time; stop the old Worker first to avoid competing polling sessions.

Required group permissions: Add New Admins, Ban Users, Restrict Members, Pin Messages.


## Hourly group notice

Set `HOURLY_CHAT_ID` in Render Environment to the numeric chat ID of the group where the hourly reminder should be sent. You can get it by adding the bot to the group and running `/id`. The bot sends the reminder once after it has been running for one hour, then every hour. The bot must be a group member and must be allowed to send messages.

Reminder text: “Next post will be pinned for an Hour (except admins) — Made by cute @oivim”, decorated with the three custom emoji IDs supplied by the owner.
