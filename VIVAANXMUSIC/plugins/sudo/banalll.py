"""
VIVAANXMUSIC |  member scan and batch banning.

Install: VIVAANXMUSIC/plugins/sudo/banall.py (or your project plugin folder).
Commands in a group (SUDO + group admin with ban rights):
    /banall          Scan accessible member IDs into RAM; show preview.
    /banall CONFIRM  Ban those IDs sequentially (permanent bans).
    /stopban         Stop scanning/banning, or discard an unconfirmed scan.

Important: Telegram may provide an incomplete member list to a bot, even an
admin bot. No assistant / userbot, database, or local file is used. RAM state
is lost on restart. The scanner uses the bot session only.

CODE OWNER: CHANDAN TIWARY: github.com/piroxpower
"""

import asyncio
import logging
import time

from pyrogram import enums, filters
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.misc import SUDOERS

log = logging.getLogger(__name__)

# Per-chat member IDs, stored only until this Python process stops.
BANLIST = {}  # {chat_id: [user_id, ...]}
PENDING = {}  # {chat_id: {"by": user_id, "expires": monotonic_timestamp}}
JOBS = {}     # {chat_id: {"task": asyncio.Task, "stop": asyncio.Event}}

DELAY_SECONDS = 1.5       # Minimum pause between processed IDs (including skips)
CONFIRM_TIMEOUT = 600     # 10 minutes to confirm the member scan
MAX_IDS = 20000           # Safety cap: stop before using excessive memory
MAX_SCAN_RETRIES = 4      # How many FloodWait interruptions to retry
MAX_API_RETRIES = 4       # How many FloodWait retries per ban/member lookup
PROGRESS_EVERY = 25       # Reuse one status message; never spam one per member

PROTECTED = (
    enums.ChatMemberStatus.OWNER,
    enums.ChatMemberStatus.ADMINISTRATOR,
)


class StopRequested(Exception):
    """An authorized user requested /stopban."""


class ScanLimitReached(Exception):
    """Telegram provided more IDs than our configured safety cap."""


async def pause_or_stop(delay, stop_event):
    """Wait without blocking the event loop, and honor /stopban immediately."""
    if stop_event.is_set():
        raise StopRequested()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, float(delay)))
    except asyncio.TimeoutError:
        return
    raise StopRequested()


async def api_call(method, *args, stop_event, **kwargs):
    """Retry Telegram FloodWait rather than skipping the current member."""
    retries = 0
    while True:
        if stop_event.is_set():
            raise StopRequested()
        try:
            return await method(*args, **kwargs)
        except FloodWait as e:
            retries += 1
            if retries > MAX_API_RETRIES:
                raise
            delay = max(1, int(e.value)) + 1
            log.warning("Telegram FloodWait (%ss), retry %s", delay, retries)
            await pause_or_stop(delay, stop_event)


async def safe_edit(message, text):
    """Optional progress updates must not crash a ban job."""
    try:
        await message.edit_text(text)
    except Exception:
        log.debug("Could not edit /banall status message", exc_info=True)


async def is_authorized(client, message, require_bot_rights=True):
    """Require a SUDO group moderator; optionally check bot ban rights."""
    if not message.from_user:
        await message.reply_text("Use this from your own admin account, not anonymously.")
        return False

    chat_id = message.chat.id
    try:
        me = getattr(client, "me", None)
        bot_id = getattr(me, "id", None) or getattr(client, "id", None)
        if not bot_id:
            bot_id = (await client.get_me()).id
        caller = await client.get_chat_member(chat_id, message.from_user.id)
        bot = (await client.get_chat_member(chat_id, bot_id)) if require_bot_rights else None
    except (RPCError, FloodWait, ValueError) as e:
        log.warning("Unable to check admin permissions in %s: %s", chat_id, e)
        await message.reply_text("Cannot verify admin rights. Please retry.")
        return False

    def can_ban(member):
        if member.status == enums.ChatMemberStatus.OWNER:
            return True
        privileges = getattr(member, "privileges", None)
        return (
            member.status == enums.ChatMemberStatus.ADMINISTRATOR
            and bool(getattr(privileges, "can_restrict_members", False))
        )
    if require_bot_rights and not can_ban(bot):
        await message.reply_text("Give the BOT admin rights with **Ban users** enabled.")
        return False
    return True


async def scan_member_ids(client, chat_id, initiator_id, stop_event):
    """Append Telegram-visible IDs to BANLIST[chat_id] using the bot alone.

    A FloodWait interrupts async-generator iteration; restart it and dedupe.
    This does not guarantee Telegram supplied all members.
    """
    BANLIST[chat_id] = []
    seen = set()
    scan_retries = 0
    me = getattr(client, "me", None)
    bot_id = getattr(me, "id", None) or getattr(client, "id", None)
    if not bot_id:
        bot_id = (await api_call(client.get_me, stop_event=stop_event)).id

    while True:
        try:
            async for member in client.get_chat_members(
                chat_id, filter=enums.ChatMembersFilter.RECENT
            ):
                if stop_event.is_set():
                    raise StopRequested()
                user = getattr(member, "user", None)
                if user is None:
                    continue
                user_id = int(user.id)
                if user_id in seen:
                    continue
                seen.add(user_id)
                if len(seen) > MAX_IDS:
                    raise ScanLimitReached()
                if user_id in (bot_id, initiator_id):
                    continue
                if bool(getattr(user, "is_bot", False)):
                    continue
                if member.status in PROTECTED:
                    continue
                if member.status in (
                    enums.ChatMemberStatus.LEFT,
                    enums.ChatMemberStatus.BANNED,
                ):
                    continue
                if member.status == enums.ChatMemberStatus.RESTRICTED and not getattr(
                    member, "is_member", False
                ):
                    continue
                BANLIST[chat_id].append(user_id)
            return len(seen)
        except FloodWait as e:
            scan_retries += 1
            if scan_retries > MAX_SCAN_RETRIES:
                raise
            delay = max(1, int(e.value)) + 1
            log.warning("Scan FloodWait %ss; resuming via fresh scan", delay)
            await pause_or_stop(delay, stop_event)


async def scanning_job(client, message, stop_event):
    chat_id = message.chat.id
    status = None
    successful = False
    try:
        status = await message.reply_text(
            "Scanning member IDs with the bot account. Send /stopban to cancel..."
        )
        seen_count = await scan_member_ids(
            client, chat_id, message.from_user.id, stop_event
        )
        if stop_event.is_set():
            raise StopRequested()
        candidates = len(BANLIST[chat_id])
        if not candidates:
            await safe_edit(status, "No eligible member IDs were available to this bot. No bans made.")
            return

        # A count mismatch can indicate Telegram delivered only part of the list.
        count_note = ""
        try:
            chat_count = await api_call(
                client.get_chat_members_count, chat_id, stop_event=stop_event
            )
            if seen_count < chat_count:
                count_note = (
                    "\nWARNING: Telegram returned fewer members than the group count "
                    f"({seen_count}/{chat_count}). This list might be incomplete."
                )
        except RPCError:
            count_note = "\nTelegram may not allow the bot to enumerate every member."

        PENDING[chat_id] = {
            "by": message.from_user.id,
            "expires": time.monotonic() + CONFIRM_TIMEOUT,
        }
        successful = True
        await safe_edit(
            status,
            f"🔍 System Scan Completed."
            f"Data Points Mapped: **{candidates}**."
            f"{count_note}\n\n"
            "**⚙️ System Status: Queued**"
        )
    except StopRequested:
        if status:
            await safe_edit(status, "Scan stopped. No bans made.")
    except ScanLimitReached:
        if status:
            await safe_edit(
                status, f"Scan exceeded the {MAX_IDS:,}-ID safety cap. "
                "No bans made; increase MAX_IDS only if needed."
            )
    except FloodWait as e:
        if status:
            await safe_edit(status, f"Telegram required too many waits ({e.value}s). "
                            "Scan aborted; no bans made.")
    except RPCError as e:
        log.warning("Bot member scan unavailable in chat %s: %s", chat_id, e)
        if status:
            await safe_edit(status, "Telegram denied or interrupted member enumeration "
                            f"({type(e).__name__}). No bans made.")
    except Exception:
        log.exception("Unexpected /banall scan failure in %s", chat_id)
        if status:
            await safe_edit(status, "Scan failed unexpectedly; see bot logs. No bans made.")
    finally:
        # /stopban may arrive while the final preview is being edited.
        if stop_event.is_set():
            successful = False
        if not successful:
            BANLIST.pop(chat_id, None)
            PENDING.pop(chat_id, None)
        if JOBS.get(chat_id, {}).get("task") is asyncio.current_task():
            JOBS.pop(chat_id, None)


async def banning_job(client, message, stop_event):
    chat_id = message.chat.id
    candidate_ids = list(BANLIST.get(chat_id, []))
    total = len(candidate_ids)
    banned = skipped = failed = processed = 0
    status = None
    try:
        status = await message.reply_text(
            f"Starting bot-only bans for {total} saved IDs. "
            "One by one; /stopban can stop this job."
        )
        bot_me = getattr(client, "me", None)
        bot_id = getattr(bot_me, "id", None) or getattr(client, "id", None)
        if not bot_id:
            bot_id = (await api_call(client.get_me, stop_event=stop_event)).id

        for user_id in candidate_ids:
            if stop_event.is_set():
                raise StopRequested()
            try:
                # Status may have changed since the scan. Never ban an admin.
                if user_id in (bot_id, message.from_user.id):
                    skipped += 1
                else:
                    member = await api_call(
                        client.get_chat_member, chat_id, user_id, stop_event=stop_event
                    )
                    user = getattr(member, "user", None)
                    if (
                        member.status in PROTECTED
                        or member.status in (
                            enums.ChatMemberStatus.BANNED,
                            enums.ChatMemberStatus.LEFT,
                        )
                        or (member.status == enums.ChatMemberStatus.RESTRICTED and
                            not getattr(member, "is_member", False))
                        or bool(getattr(user, "is_bot", False))
                    ):
                        skipped += 1
                    else:
                        await api_call(
                            client.ban_chat_member, chat_id, user_id, stop_event=stop_event
                        )
                        banned += 1
                        log.info("Banned user %s from %s", user_id, chat_id)
            except StopRequested:
                raise
            except RPCError as e:
                failed += 1
                log.warning("Ban failed for user %s in %s: %s", user_id, chat_id, e)
                if type(e).__name__ in (
                    "ChatAdminRequired", "ChatWriteForbidden", "RightForbidden",
                ):
                    await safe_edit(status, "Bot lost ban privileges. Stopped early. "
                                    f"Banned {banned}, skipped {skipped}, failed {failed}.")
                    return
            except Exception:
                failed += 1
                log.exception("Unexpected error for member %s in %s", user_id, chat_id)

            processed += 1
            if processed % PROGRESS_EVERY == 0:
                await safe_edit(
                    status, f"Processed {processed}/{total}: "
                            f"banned {banned}, skipped {skipped}, failed {failed}. "
                            "Send /stopban to stop."
                )
            if processed < total:
                await pause_or_stop(DELAY_SECONDS, stop_event)

        await safe_edit(
            status,
            f"Finished. Processed {processed}/{total} IDs.\n"
            f"Banned: {banned} | Skipped: {skipped} | Failed: {failed}."
        )
    except StopRequested:
        if status:
            await safe_edit(
                status, f"Stopped. Processed {processed}/{total} IDs.\n"
                        f"Banned: {banned} | Skipped: {skipped} | Failed: {failed}."
            )
    except Exception:
        log.exception("Unexpected /banall ban job failure in %s", chat_id)
        if status:
            await safe_edit(status, "Ban operation failed unexpectedly; see bot logs.")
    finally:
        if JOBS.get(chat_id, {}).get("task") is asyncio.current_task():
            JOBS.pop(chat_id, None)
        PENDING.pop(chat_id, None)
        BANLIST.pop(chat_id, None)


@app.on_message(filters.command("banall") & filters.group & SUDOERS)
async def banall_command(client, message: Message):
    if not await is_authorized(client, message):
        return
    chat_id = message.chat.id
    active_job = JOBS.get(chat_id)
    if active_job is not None:
        return await message.reply_text(
            "This group already has a scanning/ban job. Use /stopban to cancel."
        )

    if len(message.command) > 1 and message.command[1].upper() == "CONFIRM":
        pending = PENDING.get(chat_id)
        if not pending or time.monotonic() > pending["expires"]:
            PENDING.pop(chat_id, None)
            BANLIST.pop(chat_id, None)
            return await message.reply_text("No valid scan to confirm. Send /banall first.")
        if pending["by"] != message.from_user.id:
            return await message.reply_text("Only the admin who scanned can confirm the ban.")
        if not BANLIST.get(chat_id):
            return await message.reply_text("The RAM member list is empty. Rescan with /banall.")
        stop_event = asyncio.Event()
        task = asyncio.create_task(banning_job(client, message, stop_event))
        JOBS[chat_id] = {"task": task, "stop": stop_event}
        return

    if len(message.command) > 1:
        return await message.reply_text("Use /banall, /banall CONFIRM, or /stopban.")

    PENDING.pop(chat_id, None)
    BANLIST.pop(chat_id, None)
    stop_event = asyncio.Event()
    task = asyncio.create_task(scanning_job(client, message, stop_event))
    JOBS[chat_id] = {"task": task, "stop": stop_event}


@app.on_message(filters.command("stopban") & filters.group & SUDOERS)
async def stopban_command(client, message: Message):
    if not await is_authorized(client, message, require_bot_rights=False):
        return
    chat_id = message.chat.id
    job = JOBS.get(chat_id)
    if job:
        job["stop"].set()
        return await message.reply_text("Stop requested. The current operation will exit safely.")
    if chat_id in PENDING or chat_id in BANLIST:
        PENDING.pop(chat_id, None)
        BANLIST.pop(chat_id, None)
        return await message.reply_text("Unconfirmed member list discarded. No bans made.")
    return await message.reply_text("No /banall operation is running in this group.")
