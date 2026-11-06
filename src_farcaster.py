"""Farcaster (where many crypto founders and funds post) through Neynar's API. Optional.
Needs NEYNAR_API_KEY. Check Neynar's current free-tier limits and terms before relying on it."""
import time

import sp_config as config
import sp_db as dbm
import sp_profile as profile

URL = "https://api.neynar.com/v2/farcaster/cast/search"


def parse(resp):
    items = []
    casts = ((resp.get("result") or {}).get("casts")) or resp.get("casts") or []
    for c in casts:
        h = c.get("hash")
        if not h:
            continue
        user = (c.get("author") or {}).get("username") or "unknown"
        items.append({
            "key": "fc:" + h,
            "source": "farcaster",
            "url": "https://warpcast.com/%s/%s" % (user, h[:10]),
            "text": "@%s: %s" % (user, c.get("text", "")),
            "author": user,
            "priority": 0,
        })
    return items


async def fetch(db, deadline):
    import httpx

    key = config.cfg("NEYNAR_API_KEY")
    if not key:
        return []
    state = dbm.kv_get(db, "fc_state", {}) or {}
    force = bool(dbm.kv_get(db, "force_collect", 0))
    if not force and time.time() - state.get("last", 0) < config.cfgi("FARCASTER_INTERVAL_MIN") * 60:
        return []
    out = []
    async with httpx.AsyncClient(timeout=15) as client:
        for q in profile.load_queries().get("farcaster", []):
            if time.time() > deadline - 12:
                break
            r = await client.get(URL, params={"q": q["q"], "limit": 25}, headers={"x-api-key": key})
            if r.status_code != 200:
                state["error"] = "Neynar HTTP %s" % r.status_code
                break
            state.pop("error", None)
            out.extend(i for i in parse(r.json()) if profile.keyword_ok(i["text"]))
    state["last"] = time.time()
    dbm.kv_set(db, "fc_state", state)
    return out
