"""Your private Telegram bot. Commands and share-to-bot. Only the owner can use it."""
import hashlib
import json
import re
import time

import sp_config as config
import sp_db as dbm
import sp_notify as notify

HELP = (
    "SPARTA agents\n"
    "- Share or forward any X post, link or message to me: I will research, score and verify it, then message you the result.\n"
    "/status - queue and X usage\n"
    "/leads - top verified leads\n"
    "/search - run all sources on the next tick\n"
    "Nothing is ever sent to anyone but you."
)


async def handle(db, update):
    msg = update.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if chat_id is None or not text:
        return
    owner = config.cfg("TG_OWNER_ID")
    if not owner:
        if text.startswith("/start"):
            await notify.send_to(chat_id, "Your chat id is %s. Set TG_OWNER_ID to this number in Render and redeploy." % chat_id)
        return
    if str(chat_id) != str(owner):
        return  # ignore everyone else silently
    cmd = text.split()[0].lower() if text.startswith("/") else ""
    if cmd in ("/start", "/help"):
        await notify.send_to(chat_id, HELP)
    elif cmd == "/status":
        await notify.send_to(chat_id, status_text(db))
    elif cmd == "/leads":
        await notify.send_to(chat_id, leads_text(db))
    elif cmd == "/search":
        dbm.kv_set(db, "force_collect", 1)
        await notify.send_to(chat_id, "OK. All sources will run on the next tick (within a couple of minutes).")
    else:
        key = "shared:" + hashlib.sha1(text.encode()).hexdigest()[:20]
        item = {"key": key, "source": "shared", "url": (re.findall(r"https?://\S+", text) or [None])[0],
                "text": text, "author": "me", "priority": 10}
        if dbm.insert_item(db, item):
            await notify.send_to(chat_id, "Queued. I will message you when it is analysed (a few minutes).")
        else:
            await notify.send_to(chat_id, "I already have that one.")


def status_text(db):
    rows = db.query("SELECT stage, COUNT(*) AS n FROM leads GROUP BY stage")
    counts = ", ".join("%s %s" % (r["stage"], r["n"]) for r in rows) or "empty"
    day = time.strftime("%Y-%m-%d", time.gmtime())
    xs = dbm.kv_get(db, "x_state", {}) or {}
    reads = dbm.kv_get(db, "x_reads:" + day, 0)
    lt = dbm.kv_get(db, "last_tick", {}) or {}
    age = ("%d min ago" % ((time.time() - lt["at"]) / 60)) if lt.get("at") else "never"
    lines = ["Leads by stage: " + counts, "X posts read today: %s of %s" % (reads, config.cfg("X_DAILY_READS")), "Last tick: " + age]
    if xs.get("error"):
        lines.append("X problem: " + xs["error"])
    return "\n".join(lines)


def leads_text(db):
    rows = db.query("SELECT name, kind, score FROM leads WHERE verdict='pass' AND status='new' ORDER BY score DESC LIMIT 5")
    if not rows:
        return "No verified leads waiting yet."
    return "Top verified leads:\n" + "\n".join("%d. %s (%s, %.0f)" % (i + 1, r["name"], r["kind"], r["score"] or 0) for i, r in enumerate(rows))
