"""Reads PUBLIC Telegram channels with a separate account (Telethon). Read-only.

Risk to know: Telegram can log out a session that is used from many IPs at once. The lock
below keeps it to one reader at a time, and the session should belong to a spare account,
never your main one. This source is optional and off until all four settings are present.
"""
import asyncio
import time

import sp_config as config
import sp_db as dbm
import sp_profile as profile


async def fetch(db, deadline):
    needed = ("TG_API_ID", "TG_API_HASH", "TG_SESSION", "TG_CHANNELS")
    if not all(config.cfg(k) for k in needed):
        return []
    state = dbm.kv_get(db, "tg_state", {}) or {}
    force = bool(dbm.kv_get(db, "force_collect", 0))
    if not force and time.time() - state.get("last", 0) < config.cfgi("TG_INTERVAL_MIN") * 60:
        return []
    try:
        from telethon import TelegramClient
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
        last_ids = state.setdefault("ids", {})
        channels = [c.strip().lstrip("@") for c in config.cfg("TG_CHANNELS").split(",") if c.strip()][:5]
        for ch in channels:
            if time.time() > deadline - 12:
                break
            msgs = await client.get_messages(ch, limit=30, min_id=int(last_ids.get(ch, 0)))
            for m in msgs:
                text = (m.message or "").strip()
                if m.id > int(last_ids.get(ch, 0)):
                    last_ids[ch] = m.id
                if len(text) < 40 or not profile.keyword_ok(text):
                    continue
                out.append({
                    "key": "tg:%s:%s" % (ch, m.id),
                    "source": "telegram",
                    "url": "https://t.me/%s/%s" % (ch, m.id),
                    "text": "[channel @%s] %s" % (ch, text),
                    "author": ch,
                    "priority": 0,
                })
            await asyncio.sleep(2)  # slow on purpose
        state.pop("error", None)
    finally:
        state["last"] = time.time()
        dbm.kv_set(db, "tg_state", state)
        try:
            await client.disconnect()
        except Exception:
            pass
        dbm.unlock(db, "tgread")
    return out
