#!/usr/bin/env python3
"""
SellerSmart Support — Telegram group helper bot

Features:
- Welcome messages
- Admin promotion/demotion notices (requires chat_member updates)
- Pin notices with a preview of the pinned post
- Optional automatic unpin after a configurable duration
- Optional Telegram Premium custom emoji IDs

This bot does NOT delete ads, links, Telegram Stars links, or OTC messages.
Run with: python sellersmart.py
"""

import asyncio
import json
import logging
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import timedelta
from html import escape

from telegram import Update, MessageEntity
from telegram.constants import ChatMemberStatus, ParseMode
from telegram import ChatPermissions
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

TOKEN = os.getenv("BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
CONFIG_FILE = "sellersmart_config.json"

DEFAULT_CONFIG = {
    "pin_duration_seconds": 2 * 60 * 60,
    # User-provided Telegram Premium custom emoji IDs
    "custom_emojis": {
        "welcome": "5839317027449215441",
        "pin": "5204049355295705891",
        "admin": "5472094690826297999",
        "moderation": "5838987526148201677",
        "hourly_pin": "6231140988283263724",
        "hourly_clock": "5472094690826297999",
        "hourly_signature": "5838987526148201677",
    }
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("SellerSmart")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged
    except (OSError, json.JSONDecodeError):
        log.exception("Config could not be read; using defaults.")
        return DEFAULT_CONFIG.copy()


def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


CONFIG = load_config()


def duration_text(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400} day(s)"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} hour(s)"
    if seconds % 60 == 0:
        return f"{seconds // 60} minute(s)"
    return f"{seconds} second(s)"


def parse_duration(value: str):
    match = re.fullmatch(r"(\d+)\s*(s|m|h|d)", value.lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    if amount < 1 or seconds > 30 * 86400:
        return None
    return seconds


def display_name(user):
    name = user.full_name or user.first_name or "Member"
    return escape(name)


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        log.exception("Could not verify admin status")
        return False


def custom_emoji_entity(kind: str, offset: int, length: int):
    emoji_id = CONFIG.get("custom_emojis", {}).get(kind)
    if not emoji_id:
        return None
    return MessageEntity(
        type=MessageEntity.CUSTOM_EMOJI,
        offset=offset,
        length=length,
        custom_emoji_id=str(emoji_id),
    )


async def send_formatted(chat_id, context, kind, text):
    # A visible emoji remains as a fallback if no custom emoji ID is configured.
    prefix = "✨" if kind == "welcome" else "📌"
    body = f"{prefix} {text}"
    entities = []
    entity = custom_emoji_entity(kind, 0, len(prefix))
    if entity:
        entities.append(entity)
    await context.bot.send_message(
        chat_id=chat_id,
        text=body,
        entities=entities or None,
        parse_mode=None,
        disable_web_page_preview=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "SellerSmart Support is running. Add me to your market group and make me admin.\n\n"
        "Commands:\n"
        "/help — show commands\n"
        "/setpinduration 2h — set auto-unpin time\n"
        "/pinduration — show current duration\n"
        "/setemoji welcome EMOJI_ID — set welcome custom emoji\n"
        "/setemoji pin EMOJI_ID — set pin custom emoji\n"
        "/setemoji admin EMOJI_ID — set admin custom emoji\n"
        "/id — show your user and chat IDs"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    await update.effective_message.reply_text(
        f"Your user ID: {user.id if user else 'unknown'}\n"
        f"Chat ID: {chat.id if chat else 'unknown'}"
    )


async def set_pin_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.effective_message.reply_text("Only group admins can change this setting.")
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text(
            "Usage: /setpinduration 2h\nAccepted examples: 30m, 2h, 1d (maximum 30d)."
        )
        return
    seconds = parse_duration(context.args[0])
    if seconds is None:
        await update.effective_message.reply_text(
            "Invalid duration. Use values like 30m, 2h, or 1d (maximum 30d)."
        )
        return
    CONFIG["pin_duration_seconds"] = seconds
    save_config(CONFIG)
    await update.effective_message.reply_text(
        f"Auto-unpin duration set to {duration_text(seconds)}."
    )


async def pin_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seconds = int(CONFIG.get("pin_duration_seconds", 7200))
    await update.effective_message.reply_text(
        f"Current auto-unpin duration: {duration_text(seconds)}."
    )


async def set_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.effective_message.reply_text("Only group admins can change this setting.")
        return
    if len(context.args) != 2 or context.args[0] not in ("welcome", "pin", "admin"):
        await update.effective_message.reply_text(
            "Usage: /setemoji welcome CUSTOM_EMOJI_ID\n"
            "Or: /setemoji pin CUSTOM_EMOJI_ID\n"
            "Or: /setemoji admin CUSTOM_EMOJI_ID"
        )
        return
    kind, emoji_id = context.args
    if not emoji_id.isdigit():
        await update.effective_message.reply_text("The custom emoji ID must contain digits only.")
        return
    CONFIG.setdefault("custom_emojis", {})[kind] = emoji_id
    save_config(CONFIG)
    await update.effective_message.reply_text(f"Custom emoji for {kind} saved.")


async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.new_chat_members:
        return
    for user in message.new_chat_members:
        if user.id == context.bot.id:
            continue
        await send_formatted(
            update.effective_chat.id,
            context,
            "welcome",
            f"Welcome, {user.full_name}! ❤️\nPlease read the group rules and enjoy the market.",
        )


def is_admin_status(status):
    return status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)


async def admin_status_changed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    change = update.chat_member
    if not change:
        return
    old_admin = is_admin_status(change.old_chat_member.status)
    new_admin = is_admin_status(change.new_chat_member.status)
    user = change.new_chat_member.user
    if old_admin == new_admin:
        return

    prefix = "👑" if new_admin else "⚠️"
    if new_admin:
        text = f"{prefix} Admin update: {user.full_name} has been added as a group admin. ❤️"
    else:
        text = f"{prefix} Admin update: {user.full_name} is no longer a group admin."
    entities = []
    emoji_entity = custom_emoji_entity("admin", 0, len(prefix))
    if emoji_entity:
        entities.append(emoji_entity)
    await context.bot.send_message(
        chat_id=change.chat.id,
        text=text,
        entities=entities or None,
        disable_web_page_preview=True,
    )


async def pin_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.pinned_message:
        return

    pinned = message.pinned_message
    actor = message.from_user.full_name if message.from_user else "A group admin/member"
    seconds = int(CONFIG.get("pin_duration_seconds", 7200))

    # Telegram service messages may not expose the original author in every case.
    author = pinned.from_user.full_name if pinned.from_user else "Unknown author"
    preview = pinned.text or pinned.caption or "[Media / non-text post]"
    preview = preview.strip()
    if len(preview) > 350:
        preview = preview[:347] + "..."

    notice = (
        f"📌 Market post pinned\n\n"
        f"By: {actor}\n"
        f"Post author: {author}\n"
        f"Preview: {preview}\n\n"
        f"Auto-unpin: {duration_text(seconds)}"
    )
    pin_entity = custom_emoji_entity("pin", 0, len("📌"))
    await context.bot.send_message(
        chat_id=message.chat_id,
        text=notice,
        entities=[pin_entity] if pin_entity else None,
        disable_web_page_preview=True,
    )

    # Schedule unpin. If several posts are pinned, each job targets that message.
    context.job_queue.run_once(
        auto_unpin,
        when=timedelta(seconds=seconds),
        data={"chat_id": message.chat_id, "message_id": pinned.message_id},
        name=f"unpin:{message.chat_id}:{pinned.message_id}",
    )


async def auto_unpin(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.unpin_chat_message(
            chat_id=data["chat_id"],
            message_id=data["message_id"],
        )
        log.info("Automatically unpinned message %s", data["message_id"])
    except Exception as exc:
        # Telegram can reject this if the message was already unpinned or permissions changed.
        log.warning("Could not auto-unpin message: %s", exc)



async def target_user_id(update, context):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    if context.args and context.args[0].isdigit():
        return int(context.args[0])
    return None

async def admin_command(update, context):
    if not await is_admin(update, context):
        await update.effective_message.reply_text("Only group admins can use this command."); return
    uid = await target_user_id(update, context)
    if not uid:
        await update.effective_message.reply_text("Reply to a member or use /admin USER_ID."); return
    try:
        await context.bot.promote_chat_member(update.effective_chat.id, uid,
            can_manage_chat=True, can_delete_messages=True, can_manage_video_chats=True,
            can_restrict_members=True, can_promote_members=False, can_change_info=False,
            can_invite_users=True, can_pin_messages=True, can_manage_topics=False)
        await send_moderation_notice(update, context, f"User {uid} promoted to admin.")
    except Exception as e:
        log.warning("Promote failed: %s", e)
        await update.effective_message.reply_text("❌ Promote failed. Bot needs Add New Admins permission.")

async def unadmin_command(update, context):
    if not await is_admin(update, context):
        await update.effective_message.reply_text("Only group admins can use this command."); return
    uid = await target_user_id(update, context)
    if not uid:
        await update.effective_message.reply_text("Reply to an admin or use /unadmin USER_ID."); return
    try:
        await context.bot.promote_chat_member(update.effective_chat.id, uid,
            can_manage_chat=False, can_delete_messages=False, can_manage_video_chats=False,
            can_restrict_members=False, can_promote_members=False, can_change_info=False,
            can_invite_users=False, can_pin_messages=False, can_manage_topics=False)
        await send_moderation_notice(update, context, f"Admin rights removed from {uid}.")
    except Exception as e:
        log.warning("Demote failed: %s", e)
        await update.effective_message.reply_text("❌ Could not remove admin rights; target may have higher privileges.")

async def ban_command(update, context):
    if not await is_admin(update, context):
        await update.effective_message.reply_text("Only group admins can use this command."); return
    uid = await target_user_id(update, context)
    if not uid:
        await update.effective_message.reply_text("Reply to a member or use /ban USER_ID."); return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, uid)
        await send_moderation_notice(update, context, f"User {uid} has been banned.")
    except Exception as e:
        log.warning("Ban failed: %s", e)
        await update.effective_message.reply_text("❌ Ban failed. Check bot's Ban Users permission.")

async def unban_command(update, context):
    if not await is_admin(update, context):
        await update.effective_message.reply_text("Only group admins can use this command."); return
    uid = await target_user_id(update, context)
    if not uid:
        await update.effective_message.reply_text("Use /unban USER_ID."); return
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, uid, only_if_banned=True)
        await send_moderation_notice(update, context, f"User {uid} has been unbanned.")
    except Exception as e:
        log.warning("Unban failed: %s", e)
        await update.effective_message.reply_text("❌ Unban failed. Check bot's Ban Users permission and user ID.")

def mute_permissions(muted):
    allowed = not muted
    return ChatPermissions(can_send_messages=allowed, can_send_audios=allowed,
        can_send_documents=allowed, can_send_photos=allowed, can_send_videos=allowed,
        can_send_video_notes=allowed, can_send_voice_notes=allowed,
        can_send_polls=allowed, can_send_other_messages=allowed,
        can_add_web_page_previews=allowed)

async def mute_command(update, context):
    if not await is_admin(update, context):
        await update.effective_message.reply_text("Only group admins can use this command."); return
    uid = await target_user_id(update, context)
    if not uid:
        await update.effective_message.reply_text("Reply to a member or use /mute USER_ID."); return
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, uid, permissions=mute_permissions(True))
        await send_moderation_notice(update, context, f"User {uid} has been muted.")
    except Exception as e:
        log.warning("Mute failed: %s", e)
        await update.effective_message.reply_text("❌ Mute failed. Check bot's Restrict Members permission.")

async def unmute_command(update, context):
    if not await is_admin(update, context):
        await update.effective_message.reply_text("Only group admins can use this command."); return
    uid = await target_user_id(update, context)
    if not uid:
        await update.effective_message.reply_text("Reply to a member or use /unmute USER_ID."); return
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, uid, permissions=mute_permissions(False))
        await send_moderation_notice(update, context, f"User {uid} has been unmuted.")
    except Exception as e:
        log.warning("Unmute failed: %s", e)
        await update.effective_message.reply_text("❌ Unmute failed. Check bot's Restrict Members permission.")


async def send_moderation_notice(update, context, text):
    prefix = "🛡️"
    entity = custom_emoji_entity("moderation", 0, len(prefix))
    await update.effective_message.reply_text(
        f"{prefix} {text}",
        entities=[entity] if entity else None,
    )


def utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


async def hourly_group_notice(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    first = "📌"
    second = "⏳"
    third = "✨"
    line1 = f"{first} Next post will be pinned for an Hour (except admins)"
    line2 = f"{second} Made by @oivim {third}"
    body = line1 + "\n" + line2

    # Telegram custom-emoji entity offsets use UTF-16 code units.
    offset1 = 0
    offset2 = utf16_len(line1 + "\n")
    offset3 = utf16_len(line2[:line2.rfind(third)])
    entities = [
        MessageEntity(
            type=MessageEntity.CUSTOM_EMOJI, offset=offset1, length=utf16_len(first),
            custom_emoji_id=str(CONFIG["custom_emojis"]["hourly_pin"]),
        ),
        MessageEntity(
            type=MessageEntity.CUSTOM_EMOJI, offset=offset2, length=utf16_len(second),
            custom_emoji_id=str(CONFIG["custom_emojis"]["hourly_clock"]),
        ),
        MessageEntity(
            type=MessageEntity.CUSTOM_EMOJI, offset=offset2 + offset3, length=utf16_len(third),
            custom_emoji_id=str(CONFIG["custom_emojis"]["hourly_signature"]),
        ),
    ]
    await context.bot.send_message(
        chat_id=chat_id, text=body, entities=entities, disable_web_page_preview=True
    )


async def post_init(application: Application):
    me = await application.bot.get_me()
    log.info("Started as @%s", me.username)

    # Set HOURLY_CHAT_ID in Render to the target group's numeric chat ID.
    hourly_chat_id = os.getenv("HOURLY_CHAT_ID", "").strip()
    if hourly_chat_id:
        try:
            chat_id = int(hourly_chat_id)
            application.job_queue.run_repeating(
                hourly_group_notice,
                interval=3600,
                first=3600,
                data={"chat_id": chat_id},
                name=f"hourly-group-notice:{chat_id}",
            )
            log.info("Hourly group notice scheduled for chat %s", chat_id)
        except ValueError:
            log.error("HOURLY_CHAT_ID must be a numeric Telegram group ID")
    else:
        log.warning("HOURLY_CHAT_ID is not set; hourly group notice is disabled")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            body = b"SellerSmart bot is running"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        # Keep Render logs focused on bot activity.
        log.info("Health endpoint: " + format, *args)


def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Web health server listening on 0.0.0.0:%s", port)
    return server


def main():
    if TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE" or not TOKEN.strip():
        raise SystemExit(
            "Set your bot token first. Example:\n"
            "export BOT_TOKEN='123456:ABC...'\n"
            "python sellersmart.py"
        )

    # Render Web Services require an HTTP listener on the assigned PORT.
    start_health_server()

    # Render can have occasional slow outbound connections to api.telegram.org.
    # Use longer HTTP timeouts so a brief network delay does not kill the worker.
    normal_request = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    polling_request = HTTPXRequest(
        connection_pool_size=2,
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    app = (
        Application.builder()
        .token(TOKEN)
        .request(normal_request)
        .get_updates_request(polling_request)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("setpinduration", set_pin_duration))
    app.add_handler(CommandHandler("pinduration", pin_duration))
    app.add_handler(CommandHandler("setemoji", set_emoji))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("unadmin", unadmin_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unmute", unmute_command))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, pin_event))
    app.add_handler(ChatMemberHandler(admin_status_changed, ChatMemberHandler.CHAT_MEMBER))

    # Request chat_member updates so admin promotion/demotion events are delivered.
    log.info("Starting SellerSmart polling; HTTP timeouts: connect=30s read=60s")
    app.run_polling(
        bootstrap_retries=-1,
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=30.0,
        pool_timeout=30.0,
        allowed_updates=[
            "message",
            "edited_message",
            "chat_member",
            "my_chat_member",
        ]
    )


if __name__ == "__main__":
    # Ensure an event loop exists on newer Python runtimes before PTB starts polling.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    main()
