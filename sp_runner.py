"""One 'tick' = a short, time-boxed slice of work. Your pinger calls it every minute or two.

Why: serverless functions cannot run forever. State (queue, rate limits, cursors) lives in the
database, so each tick picks up exactly where the last one stopped.
"""
import json
import time

import sp_config as config
import sp_db as dbm
import sp_pipeline as pipeline
import sp_profile as profile
import src_defillama
import src_farcaster
import src_reddit
import src_telegram
import src_web
import src_x

# Free and cheap sources go first so the per tick cap never starves them.
SOURCES = [
    ("defillama", src_defillama),
    ("telegram", src_telegram),
    ("x", src_x),
    ("farcaster", src_farcaster),
    ("reddit", src_reddit),
    ("web", src_web),
]
OPEN_STAGES = ("new", "triaged", "scored", "verified")
RANK = {"verified": 0, "scored": 1, "triaged": 2, "new": 3}  # finish started work first


def pending_count(db):
    rows = db.query("SELECT COUNT(*) AS n FROM leads WHERE stage IN ('new','triaged','scored','verified')")
    return int(rows[0]["n"]) if rows else 0


def enqueue(db, items, max_new):
    """Insert new raw items, applying keyword prefilter and daily cap. Returns count inserted."""
    day = time.strftime("%Y-%m-%d", time.gmtime())
    key = "items:" + day
    today_n = dbm.kv_get(db, key, 0) or 0
    cap = config.cfgi("DAILY_ITEM_CAP")
    added = 0
    for it in items:
        if added >= max_new:
            break
        shared = it.get("source") == "shared"
        if not shared and today_n + added >= cap:
            break
        if not shared and it.get("source") in ("x", "telegram", "farcaster", "reddit") and not profile.keyword_ok(it.get("text", "")):
            continue
        if dbm.insert_item(db, it):
            added += 1
    dbm.kv_set(db, key, today_n + added)
    return added


async def collect(db, deadline, summary):
    total = 0
    for name, mod in SOURCES:
        if time.time() > deadline - 15 or total >= config.cfgi("MAX_NEW_PER_TICK"):
            break
        try:
            items = await mod.fetch(db, deadline)
        except Exception as e:
            summary["errors"].append("%s: %s: %s" % (name, type(e).__name__, str(e)[:900]))
            continue
        n = enqueue(db, items, config.cfgi("MAX_NEW_PER_TICK") - total)
        summary["sources"][name] = n
        total += n
    return total


def next_row(db, remaining):
    rows = db.query(
        "SELECT * FROM leads WHERE stage IN ('new','triaged','scored','verified') AND next_try <= ? "
        "ORDER BY priority DESC, created_at ASC LIMIT 30",
        (time.time(),),
    )
    rows.sort(key=lambda r: (-(r.get("priority") or 0), RANK.get(r["stage"], 9), r.get("created_at") or 0))
    for r in rows:
        if pipeline.NEED[r["stage"]] <= remaining:
            return r
    return None


async def process(db, deadline, summary):
    done = 0
    for _ in range(12):
        remaining = deadline - time.time()
        row = next_row(db, remaining)
        if not row:
            break
        await pipeline.advance(db, row, remaining)
        done += 1
    return done


async def tick(db, budget=None):
    budget = budget or config.cfgi("TICK_SECONDS")
    deadline = time.time() + budget
    if not dbm.lock(db, "tick", budget + 20):
        return {"skipped": "another tick is running"}
    summary = {"sources": {}, "errors": [], "processed": 0, "pending": 0}
    started = time.time()
    try:
        if pending_count(db) < config.cfgi("QUEUE_MAX"):
            await collect(db, deadline, summary)
        summary["processed"] = await process(db, deadline, summary)
        summary["pending"] = pending_count(db)
        dbm.kv_set(db, "force_collect", 0)
    finally:
        summary["seconds"] = round(time.time() - started, 1)
        dbm.kv_set(db, "last_tick", {"at": time.time(), **summary})
        dbm.unlock(db, "tick")
    return summary
