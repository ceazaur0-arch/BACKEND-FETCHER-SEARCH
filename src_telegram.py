"""Searches ALL public Telegram channels and groups by keyword (Telegram global search).
No channel list needed. Read-only, uses a separate account (Telethon).

Needs a logged in user session (TG_API_ID, TG_API_HASH, TG_SESSION). Telegram does not allow
global search without a login, and a bot token cannot do it. Use a spare account, never your
main one. Optional: TG_CHANNELS adds specific channels on top of the search.

Kept slow on purpose: 2 searches per run, rotating through the saved queries, and it stops
at once if Telegram asks it to wait (flood wait).
"""
import asyncio
import time

import sp_config as config
import sp_db as dbm
import sp_profile as profile

MAX_AGE_DAYS = 14


def build_item(chat, m):
    """Turn one search hit into a lead item. Only public chats (with a username) are kept."""
    username = getattr(chat, "username", None)
    text = (getattr(m, "message", "") or "").strip()
    if not username or len(text) < 40 or not profile.keyword_ok(text):
        return None
    return {
        "key": "tg:%s:%s" % (username, m.id),
        "source": "telegram",
        "url": "https://t.me/%s/%s" % (username, m.id),
        "text": "[public chat @%s] %s" % (username, text),
        "author": username,
        "priority": 0,
    }


async def search_global(client, q, limit=20):
    from telethon import functions, types

    res = await client(functions.messages.SearchGlobalRequest(
        q=q,
        filter=types.InputMessagesFilterEmpty(),
        min_date=None,
        max_date=None,
        offset_rate=0,
        offset_peer=types.InputPeerEmpty(),
        offset_id=0,
        limit=limit,
    ))
    chats = {c.id: c for c in (getattr(res, "chats", None) or [])}
    cutoff = time.time() - MAX_AGE_DAYS * 86400
    out = []
    for m in getattr(res, "messages", None) or []:
        if not getattr(m, "date", None) or m.date.timestamp() < cutoff:
            continue
        peer = getattr(m, "peer_id", None)
        chat = chats.get(getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None))
        item = build_item(chat, m) if chat else None
        if item:
            out.append(item)
    return out


async def fetch(db, deadline):
    needed = ("TG_API_ID", "TG_API_HASH", "TG_SESSION")
    if not all(config.cfg(k) for k in needed):
        return []
    state = dbm.kv_get(db, "tg_state", {}) or {}
    force = bool(dbm.kv_get(db, "force_collect", 0))
    if time.time() < state.get("wait_until", 0):
        return []  # Telegram told us to wait
    if not force and time.time() - state.get("last", 0) < config.cfgi("TG_INTERVAL_MIN") * 60:
        return []
    try:
        from telethon import TelegramClient
        from telethon.errors import FloodWaitError
        from telethon.sessions import StringSession
    except ImportError:
        state["error"] = "telethon is not installed"
        dbm.kv_set(db, "tg_state", state)
        return []
    if not dbm.lock(db, "tgread", 90):
        return []
    out = []
    client = TelegramClient(StringSession(config.cfg("TG_SESSION")), int(config.cfg("TG_API_ID")), config.cfg("TG_API_HASH"))
    try:
        await client.connect()
        if not await client.is_user_authorized():
            state["error"] = "session is not logged in - generate a new TG_SESSION"
            return []
        queries = profile.load_queries().get("telegram", [])
        per_run = config.cfgi("TG_SEARCHES_PER_RUN")
        cursor = int(state.get("cursor", 0))
        errors = []
        for i in range(min(per_run, len(queries))):
            if time.time() > deadline - 12:
                break
            q = queries[(cursor + i) % len(queries)]
            try:
                out.extend(await search_global(client, q["q"]))
            except FloodWaitError as e:
                state["wait_until"] = time.time() + int(getattr(e, "seconds", 600)) + 30
                errors.append("Telegram asked to wait %ss" % getattr(e, "seconds", "?"))
                break
            except Exception as e:
                errors.append("search '%s': %s" % (q["q"], str(e)[:150]))
            await asyncio.sleep(3)  # slow on purpose
        state["cursor"] = (cursor + per_run) % max(len(queries), 1)

        # optional: specific channels on top of the search
        last_ids = state.setdefault("ids", {})
        channels = [c.strip().lstrip("@") for c in config.cfg("TG_CHANNELS").split(",") if c.strip()][:5]
        for ch in channels:
            if time.time() > deadline - 12:
                break
            try:
                msgs = await client.get_messages(ch, limit=30, min_id=int(last_ids.get(ch, 0)))
            except Exception as e:
                errors.append("channel @%s: %s" % (ch, str(e)[:150]))
                continue
            for m in msgs:
                text = (m.message or "").strip()
                if m.id > int(last_ids.get(ch, 0)):
                    last_ids[ch] = m.id
                if len(text) < 40 or not profile.keyword_ok(text):
                    continue
                out.append({"key": "tg:%s:%s" % (ch, m.id), "source": "telegram",
                            "url": "https://t.me/%s/%s" % (ch, m.id),
                            "text": "[channel @%s] %s" % (ch, text), "author": ch, "priority": 0})
            await asyncio.sleep(2)
        if errors:
            state["error"] = "; ".join(errors)[:400]
        else:
            state.pop("error", None)
        state["last_items"] = len(out)
    finally:
        state["last"] = time.time()
        dbm.kv_set(db, "tg_state", state)
        try:
            await client.disconnect()
        except Exception:
            pass
        dbm.unlock(db, "tgread")
    return out
