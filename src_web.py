"""Open-web discovery with Gemini + Google Search grounding. One saved task per run, rotating."""
import hashlib
import time

import sp_config as config
import sp_db as dbm
import sp_llm as llm
import sp_pipeline as pipeline
import sp_profile as profile

PROMPT = """### TASK: WEB_DISCOVERY
@@RULES@@
Today is @@TODAY@@. Search public web pages and indexed public social posts for: @@TASK@@
Prioritise first-person statements of intent: actively investing, deploying capital, acquiring/buying projects, seeking equity/co-founders, hiring, or seeking strategic partners. Search across company sites, X public posts (x.com/twitter.com), Farcaster/Warpcast, public Telegram channel pages (t.me), Reddit and the wider web where indexed.
Return up to 6 REAL, recent and directly relevant results. Prefer the original post or announcement URL, identify the person/company where possible, state the exact intent and date, and skip stale, closed, speculative or unverifiable claims. Never invent a URL or imply that a person has funds available without evidence.
JSON: [{"name": "", "url": "https://...", "summary": "specific stated intent and dated fact", "date": "YYYY-MM or unknown"}]"""


async def fetch(db, deadline):
    force = bool(dbm.kv_get(db, "force_collect", 0))
    state = dbm.kv_get(db, "web_state", {}) or {}
    manual = dbm.kv_get(db, "manual_web_search", None)
    if not force and not manual and time.time() - state.get("last", 0) < config.cfgi("WEB_INTERVAL_MIN") * 60:
        return []
    remaining = deadline - time.time()
    if remaining < 28 or not config.cfg("GEMINI_API_KEY"):
        return []
    tasks = profile.load_queries().get("web", [])
    if manual and isinstance(manual, dict) and manual.get("query"):
        task = {"id": "manual", "kind": "opportunity", "q": str(manual["query"])[:300]}
    else:
        if not tasks:
            return []
        idx = int(state.get("idx", 0)) % len(tasks)
        task = tasks[idx]
    prompt = pipeline.fill(PROMPT, RULES=pipeline.RULES, TODAY=pipeline.today(), TASK=task["q"])
    text, _ = await llm.generate(prompt, grounded=True, timeout=min(40, remaining - 4))
    if task.get("id") == "manual":
        dbm.kv_set(db, "manual_web_search", None)
    else:
        state["idx"] = (int(state.get("idx", 0)) + 1) % max(1, len(tasks))
    state["last"] = time.time()
    state.pop("error", None)
    dbm.kv_set(db, "web_state", state)
    res = llm.extract_json(text)
    if isinstance(res, dict):
        res = [res]
    out = []
    for r in res if isinstance(res, list) else []:
        if not isinstance(r, dict) or not pipeline.safety.is_http(str(r.get("url") or "")):
            continue
        url = r["url"].strip()
        out.append({
            "key": "web:" + hashlib.sha1(url.encode()).hexdigest()[:20],
            "source": "web",
            "url": url,
            "text": "[hint: kind=%s] %s - %s (%s)" % (task.get("kind", "?"), r.get("name", ""), r.get("summary", ""), r.get("date", "unknown")),
            "author": None,
            "priority": 0,
        })
    return out
