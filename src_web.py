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
Today is @@TODAY@@. Search the web for: @@TASK@@
Return up to 6 REAL, currently relevant results you actually found. Skip anything old, closed or unverifiable.
JSON: [{"name": "", "url": "https://...", "summary": "one sentence with the key dated fact", "date": "YYYY-MM or unknown"}]"""


async def fetch(db, deadline):
    force = bool(dbm.kv_get(db, "force_collect", 0))
    state = dbm.kv_get(db, "web_state", {}) or {}
    if not force and time.time() - state.get("last", 0) < config.cfgi("WEB_INTERVAL_MIN") * 60:
        return []
    remaining = deadline - time.time()
    if remaining < 28 or not config.cfg("GEMINI_API_KEY"):
        return []
    tasks = profile.load_queries().get("web", [])
    if not tasks:
        return []
    idx = int(state.get("idx", 0)) % len(tasks)
    task = tasks[idx]
    prompt = pipeline.fill(PROMPT, RULES=pipeline.RULES, TODAY=pipeline.today(), TASK=task["q"])
    text, _ = await llm.generate(prompt, grounded=True, timeout=min(40, remaining - 4))
    state["idx"] = idx + 1
    state["last"] = time.time()
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
