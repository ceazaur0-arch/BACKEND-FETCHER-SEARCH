"""Reddit via the official API (app-only OAuth). Optional. Needs REDDIT_CLIENT_ID and
REDDIT_CLIENT_SECRET. Reddit may require approval for new API apps; check their current rules."""
import time

import sp_config as config
import sp_db as dbm
import sp_profile as profile

UA = "sparta-research-bot/1.0 (read-only founder research)"


def parse(resp):
    items = []
    for ch in ((resp.get("data") or {}).get("children")) or []:
        d = ch.get("data") or {}
        if not d.get("id"):
            continue
        items.append({
            "key": "reddit:" + d["id"],
            "source": "reddit",
            "url": "https://www.reddit.com" + d.get("permalink", ""),
            "text": "r/%s: %s\n%s" % (d.get("subreddit", ""), d.get("title", ""), (d.get("selftext") or "")[:1200]),
            "author": d.get("author"),
            "priority": 0,
        })
    return items


async def fetch(db, deadline):
    import httpx

    cid, secret = config.cfg("REDDIT_CLIENT_ID"), config.cfg("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return []
    state = dbm.kv_get(db, "reddit_state", {}) or {}
    force = bool(dbm.kv_get(db, "force_collect", 0))
    if not force and time.time() - state.get("last", 0) < config.cfgi("REDDIT_INTERVAL_MIN") * 60:
        return []
    out = []
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as client:
        tr = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(cid, secret),
            data={"grant_type": "client_credentials"},
        )
        if tr.status_code != 200 or "access_token" not in tr.json():
            state["error"] = "Reddit token HTTP %s" % tr.status_code
            state["last"] = time.time()
            dbm.kv_set(db, "reddit_state", state)
            return []
        headers = {"Authorization": "bearer " + tr.json()["access_token"]}
        subs = [s.strip() for s in config.cfg("REDDIT_SUBS").split(",") if s.strip()][:4]
        for sub in subs:
            for q in profile.load_queries().get("reddit", []):
                if time.time() > deadline - 12:
                    break
                r = await client.get(
                    "https://oauth.reddit.com/r/%s/search" % sub,
                    params={"q": q["q"], "restrict_sr": 1, "sort": "new", "t": "week", "limit": 25},
                    headers=headers,
                )
                if r.status_code != 200:
                    state["error"] = "Reddit HTTP %s" % r.status_code
                    continue
                state.pop("error", None)
                out.extend(i for i in parse(r.json()) if profile.keyword_ok(i["text"]))
    state["last"] = time.time()
    dbm.kv_set(db, "reddit_state", state)
    return out
