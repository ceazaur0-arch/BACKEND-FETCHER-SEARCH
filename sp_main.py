"""FastAPI app. Render runs it with: uvicorn sp_main:app --host 0.0.0.0 --port $PORT"""
import hashlib
import hmac
import json
import time

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sp_config as config
import sp_db as dbm
import sp_runner as runner
import sp_tgbot as tgbot

app = FastAPI(title="SPARTA agents", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config.cfg("FRONTEND_ORIGIN").split(",") if o.strip()] or ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

STATUSES = {"new", "approved", "sent", "rejected", "needs_check"}


def db():
    return dbm.get_db()


def _same(a, b):
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def require_dashboard(authorization):
    token = config.cfg("DASHBOARD_TOKEN")
    if not token:
        raise HTTPException(503, "DASHBOARD_TOKEN is not set on the server")
    supplied = (authorization or "")
    if supplied.lower().startswith("bearer "):
        supplied = supplied[7:]
    if not _same(supplied.strip(), token):
        raise HTTPException(401, "bad token")


def require_cron(key):
    secret = config.cfg("CRON_KEY")
    if not secret:
        raise HTTPException(503, "CRON_KEY is not set on the server")
    if not _same(key, secret):
        raise HTTPException(401, "bad key")


def public_lead(r):
    data = json.loads(r.get("data") or "{}")
    d = data.get("dossier") or {}
    return {
        "id": r["id"],
        "source": r["source"],
        "url": r.get("url"),
        "kind": r.get("kind"),
        "name": r.get("name"),
        "score": r.get("score"),
        "verdict": r.get("verdict"),
        "status": r.get("status"),
        "summary": d.get("summary") or (data.get("triage") or {}).get("summary"),
        "facts": d.get("facts") or [],
        "decision_maker": d.get("decision_maker"),
        "contact_route": d.get("contact_route"),
        "red_flags": d.get("red_flags") or [],
        "concerns": (data.get("verification") or {}).get("concerns") or [],
        "warnings": data.get("warnings") or [],
        "draft": (data.get("draft") or {}).get("message"),
        "short": (data.get("draft") or {}).get("short"),
        "created_at": r.get("created_at"),
    }


@app.get("/")
def root():
    return {"app": "SPARTA agents", "ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "time": time.time()}


@app.get("/api/stats")
def stats(authorization: str = Header(default="")):
    require_dashboard(authorization)
    d = db()
    stages = {r["stage"]: r["n"] for r in d.query("SELECT stage, COUNT(*) AS n FROM leads GROUP BY stage")}
    day = time.strftime("%Y-%m-%d", time.gmtime())
    xs = dbm.kv_get(d, "x_state", {}) or {}
    rl = dbm.kv_get(d, "rl:x", {}) or {}
    return {
        "stages": stages,
        "x_reads_today": dbm.kv_get(d, "x_reads:" + day, 0),
        "x_daily_cap": config.cfgi("X_DAILY_READS"),
        "x_error": xs.get("error"),
        "x_resting_until": rl.get("rest_until", 0),
        "items_today": dbm.kv_get(d, "items:" + day, 0),
        "last_tick": dbm.kv_get(d, "last_tick", {}),
        "configured": {
            "gemini": bool(config.cfg("GEMINI_API_KEY")),
            "x": bool(config.cfg("X_BEARER_TOKEN")),
            "x_public_web": bool(config.cfg("GEMINI_API_KEY")),
            "telegram_bot": bool(config.cfg("TG_BOT_TOKEN") and config.cfg("TG_OWNER_ID")),
            "telegram_reader": bool(config.cfg("TG_SESSION") and config.cfg("TG_CHANNELS")),
            "telegram_discovery": bool(config.cfg("GEMINI_API_KEY")),
            "farcaster": bool(config.cfg("NEYNAR_API_KEY")),
            "reddit": bool(config.cfg("REDDIT_CLIENT_ID") and config.cfg("REDDIT_CLIENT_SECRET")),
            "web": bool(config.cfg("GEMINI_API_KEY")),
        },
        "source_activity": {
            "x": dbm.kv_get(d, "x_state", {}) or {},
            "telegram": dbm.kv_get(d, "tg_state", {}) or {},
            "farcaster": dbm.kv_get(d, "fc_state", {}) or {},
            "reddit": dbm.kv_get(d, "reddit_state", {}) or {},
            "web": dbm.kv_get(d, "web_state", {}) or {},
        },
    }


@app.get("/api/leads")
def leads(authorization: str = Header(default=""), include: str = Query(default="")):
    require_dashboard(authorization)
    sql = "SELECT * FROM leads WHERE stage='done'"
    if include != "all":
        sql += " AND status<>'hidden'"
    sql += " ORDER BY updated_at DESC LIMIT 300"
    rows = db().query(sql)
    out = [public_lead(r) for r in rows]
    out.sort(key=lambda x: -(x["score"] or 0))
    return {"leads": out}


class StatusBody(BaseModel):
    status: str


class DraftBody(BaseModel):
    message: str


class SubmitBody(BaseModel):
    text: str


class DiscoverySearchBody(BaseModel):
    query: str


@app.post("/api/discovery/run")
def discovery_run(authorization: str = Header(default="")):
    """Request one low-volume collection cycle on the next cron tick."""
    require_dashboard(authorization)
    dbm.kv_set(db(), "force_collect", 1)
    return {"queued": True, "message": "Discovery is queued for the next scheduled tick."}


@app.post("/api/discovery/search")
def discovery_search(body: DiscoverySearchBody, authorization: str = Header(default="")):
    """Queue one Gemini-grounded public-web/social-index search for a custom topic."""
    require_dashboard(authorization)
    query = (body.query or "").strip()
    if len(query) < 3:
        raise HTTPException(400, "Enter at least 3 characters.")
    if len(query) > 300:
        raise HTTPException(400, "Search query must be 300 characters or fewer.")
    if not config.cfg("GEMINI_API_KEY"):
        raise HTTPException(503, "GEMINI_API_KEY is not configured.")
    d = db()
    dbm.kv_set(d, "manual_web_search", {"query": query, "requested_at": time.time()})
    dbm.kv_set(d, "force_collect", 1)
    return {"queued": True, "message": "Your public-web search is queued for the next scheduled tick."}


@app.post("/api/leads/{lead_id}/status")
def set_status(lead_id: str, body: StatusBody, authorization: str = Header(default="")):
    require_dashboard(authorization)
    if body.status not in STATUSES:
        raise HTTPException(400, "bad status")
    dbm.update_lead(db(), lead_id, status=body.status)
    return {"ok": True}


@app.post("/api/leads/{lead_id}/draft")
def set_draft(lead_id: str, body: DraftBody, authorization: str = Header(default="")):
    require_dashboard(authorization)
    rows = db().query("SELECT data FROM leads WHERE id=?", (lead_id,))
    if not rows:
        raise HTTPException(404, "not found")
    data = json.loads(rows[0]["data"] or "{}")
    data.setdefault("draft", {})["message"] = body.message[:3000]
    dbm.update_lead(db(), lead_id, data=data)
    return {"ok": True}


@app.post("/api/submit")
def submit(body: SubmitBody, authorization: str = Header(default="")):
    require_dashboard(authorization)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty")
    item = {"key": "shared:" + hashlib.sha1(text.encode()).hexdigest()[:20], "source": "shared",
            "url": None, "text": text[:4000], "author": "me", "priority": 10}
    return {"queued": dbm.insert_item(db(), item)}


@app.get("/api/cron/tick")
async def cron_tick(background: BackgroundTasks, key: str = Query(default=""), wait: int = Query(default=0)):
    """Called by your pinger. Replies at once and does the work after replying, because free
    pingers give up after about 30 seconds. Add &wait=1 to run it inline and see the result."""
    require_cron(key)
    if wait:
        return await runner.tick(db())
    background.add_task(runner.tick, db())
    return {"started": True}


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    secret = config.cfg("TG_WEBHOOK_SECRET")
    if secret and not _same(request.headers.get("x-telegram-bot-api-secret-token", ""), secret):
        raise HTTPException(403, "bad secret")
    update = await request.json()
    await tgbot.handle(db(), update)
    return {"ok": True}


@app.get("/api/telegram/setup")
async def telegram_setup(request: Request, key: str = Query(default="")):
    """Open this URL once in your browser to connect the bot."""
    import httpx

    require_cron(key)
    token, secret = config.cfg("TG_BOT_TOKEN"), config.cfg("TG_WEBHOOK_SECRET")
    if not token or not secret:
        raise HTTPException(400, "set TG_BOT_TOKEN and TG_WEBHOOK_SECRET first")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    url = "https://%s/api/telegram/webhook" % host
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.telegram.org/bot%s/setWebhook" % token,
            json={"url": url, "secret_token": secret, "allowed_updates": ["message"]},
        )
    return {"webhook": url, "telegram_says": r.json()}
