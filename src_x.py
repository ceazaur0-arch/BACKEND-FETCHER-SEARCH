"""X (Twitter) via the OFFICIAL API only. Read-only: no posting, liking, following or DMs.

Rate rule you asked for: up to 20 searches per minute, then a 10 minute rest (X_BURST,
X_WINDOW, X_REST). A daily cap on posts read (X_DAILY_READS) controls cost, because
pay-per-use bills each post returned. since_id is stored so the same posts are never re-read.
"""
import time

import sp_config as config
import sp_db as dbm
import sp_notify as notify
import sp_profile as profile
import sp_ratelimit as ratelimit

SEARCH_URL = "https://api.x.com/2/tweets/search/recent"


def cooldown_from_headers(headers, now, status):
    """Seconds to stay quiet, from X's own rate-limit headers. 0 = carry on.

    429 -> wait until the reset time. 200 with at most 1 call left -> wait for the reset too.
    """
    try:
        reset = float(headers.get("x-rate-limit-reset", 0))
        remaining = headers.get("x-rate-limit-remaining")
        remaining = int(remaining) if remaining is not None else None
    except (TypeError, ValueError):
        return 900 if status == 429 else 0
    until = max(0.0, reset - now) + 5 if reset else 0
    if status == 429:
        return min(max(until, 60), 3600)
    if remaining is not None and remaining <= 1 and until:
        return min(until, 3600)
    return 0


def parse(resp, qid):
    """Turn an X API v2 search response into items. Returns (items, newest_id)."""
    users = {u["id"]: u for u in (resp.get("includes") or {}).get("users", [])}
    items, newest = [], None
    for t in resp.get("data") or []:
        tid = t.get("id")
        if not tid:
            continue
        u = users.get(t.get("author_id"), {})
        handle = u.get("username") or "i"
        pm = t.get("public_metrics") or {}
        text = "@%s (%s followers): %s" % (handle, (u.get("public_metrics") or {}).get("followers_count", "?"), t.get("text", ""))
        items.append({
            "key": "x:" + tid,
            "source": "x",
            "url": "https://x.com/%s/status/%s" % (handle, tid),
            "text": text + " [likes %s, reposts %s]" % (pm.get("like_count", 0), pm.get("retweet_count", 0)),
            "author": handle,
            "priority": 0,
        })
        if newest is None or int(tid) > int(newest):
            newest = tid
    return items, newest


async def fetch(db, deadline):
    import httpx

    token = config.cfg("X_BEARER_TOKEN")
    if not token:
        return []
    state = dbm.kv_get(db, "x_state", {}) or {}
    now = time.time()
    if now < state.get("disabled_until", 0):
        return []
    day = time.strftime("%Y-%m-%d", time.gmtime())
    reads_key = "x_reads:" + day
    reads = dbm.kv_get(db, reads_key, 0) or 0
    cap = config.cfgi("X_DAILY_READS")
    per = max(10, min(100, config.cfgi("X_MAX_RESULTS")))
    force = bool(dbm.kv_get(db, "force_collect", 0))
    interval = config.cfgi("X_QUERY_INTERVAL_MIN") * 60
    last = state.setdefault("last", {})
    since = state.setdefault("since", {})
    out = []
    searched = 0
    max_queries = max(1, min(5, config.cfgi("X_MAX_QUERIES_PER_RUN")))
    async with httpx.AsyncClient(timeout=15) as client:
        for q in profile.load_queries().get("x", []):
            if time.time() > deadline - 12:
                break
            qid = q["id"]
            if not force and time.time() - last.get(qid, 0) < interval:
                continue
            if searched >= max_queries:
                break
            if reads + per > cap:
                state["capped_on"] = day
                break
            ok, wait = ratelimit.acquire(db, "x", config.cfgi("X_BURST"), config.cfgi("X_WINDOW"), config.cfgi("X_REST"))
            if not ok:
                break  # resting; the next tick continues from where we stopped
            params = {
                "query": q["q"][:500],
                "max_results": per,
                "tweet.fields": "created_at,public_metrics,author_id",
                "expansions": "author_id",
                "user.fields": "username,public_metrics",
            }
            if since.get(qid):
                params["since_id"] = since[qid]
            r = await client.get(SEARCH_URL, params=params, headers={"Authorization": "Bearer " + token})
            last[qid] = time.time()
            searched += 1
            wait = cooldown_from_headers(r.headers, time.time(), r.status_code)
            if r.status_code == 200:
                items, newest = parse(r.json(), qid)
                reads += len(items)
                if newest:
                    since[qid] = newest
                out.extend(items)
                state.pop("error", None)
                if wait:  # X says we are nearly out of allowance: stop early instead of hitting the wall
                    state["disabled_until"] = time.time() + wait
                    break
            elif r.status_code in (401, 403):
                state["error"] = "X rejected the token or app (HTTP %s). The app may be suspended or restricted: check developer.x.com." % r.status_code
                state["disabled_until"] = time.time() + 6 * 3600
                break
            elif r.status_code in (402, 429):
                state["error"] = "X says out of credits or rate limited (HTTP %s)." % r.status_code
                state["disabled_until"] = time.time() + (6 * 3600 if r.status_code == 402 else (wait or 900))
                break
            else:
                state["error"] = "X error HTTP %s" % r.status_code
                state["disabled_until"] = time.time() + 1800
                break
    # Tell the owner once per problem, so a silent failure never goes unnoticed.
    if state.get("error") and state.get("alerted") != state["error"]:
        try:
            await notify.send_owner("X search paused: %s It cools down automatically and will retry. Everything else keeps running." % state["error"])
        except Exception:
            pass
        state["alerted"] = state["error"]
    elif not state.get("error"):
        state.pop("alerted", None)
    dbm.kv_set(db, reads_key, reads)
    dbm.kv_set(db, "x_state", state)
    return out
