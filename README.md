# SPARTA Deal Intelligence — backend

FastAPI backend for SPARTA. It discovers public signals about investors, buyers, equity partners, hiring, funding and strategic partnerships; Gemini then triages, researches, verifies and drafts outreach. Nothing is automatically sent to a prospect.

## Discovery sources and access

- **X:** Optional official X API read-only search (`X_BEARER_TOKEN`). API access/usage may cost money. The default is deliberately low-volume: 2 queries per tick, 10 results per API query (X's API minimum), 30 returned posts/day, and each saved query no more than once per 24 hours. When no X API token is set, Gemini Google Search grounding can still find *publicly indexed* X posts as part of rotating web discovery. This is not a full live X search.
- **Telegram:** Gemini web discovery can find public `t.me` channel pages and public indexed announcements. Reading message history requires an authorised Telegram user session and configured channel usernames (`TG_API_ID`, `TG_API_HASH`, `TG_SESSION`, `TG_CHANNELS`). The reader only reads configured public channels; it does not automatically crawl all of Telegram or silently add channels to your session.
- **Farcaster:** Neynar cast search (`NEYNAR_API_KEY`).
- **Reddit:** Reddit app-only OAuth (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`) for the subreddits in `REDDIT_SUBS`.
- **Web:** Gemini Google Search grounding searches a rotating set of discovery tasks across company sites and publicly indexed social posts. The dashboard can queue a custom public-web query.
- **DefiLlama:** Public funding-round dataset.

No X account password, browser cookies, private Telegram messages, or access-control bypass is used. Public web indexing is not guaranteed to include every post or platform.

## Pipeline

1. Collect public source items.
2. Apply a lightweight keyword prefilter and daily queue cap.
3. Gemini triage classifies the signal (investor, grant, buyer, equity, job, partnership).
4. Gemini researches a sourced dossier and scores fit.
5. A separate verifier tries to disprove claims and checks for scam signals.
6. Only verified leads receive an outreach draft. You review and send it yourself.

The original source URL is preserved. A lead is not considered verified merely because its wording sounds convincing.

## Deploy on Render

- Build: `pip install -r requirements.txt`
- Start: `uvicorn sp_main:app --host 0.0.0.0 --port $PORT`
- Health: `/api/health`

Set these environment variables in Render:
- `DATABASE_URL` — Neon pooled PostgreSQL URL.
- `DASHBOARD_TOKEN` — long random server-only signing secret (never enter it in the frontend).
- `ADMIN_EMAIL` — your administrator sign-in email.
- `ADMIN_PASSWORD` — a strong, unique administrator password.
- `CRON_KEY` — separate long random secret you create.
- `GEMINI_API_KEY` — Google AI Studio API key.
- `FRONTEND_ORIGIN` — exact Vercel frontend origin, e.g. `https://your-project.vercel.app`.

Optional:
- `TG_BOT_TOKEN`, `TG_WEBHOOK_SECRET`, `TG_OWNER_ID` for private Telegram alerts/share-to-bot.
- `X_BEARER_TOKEN` only if you have authorised official X API access and accept its usage charges.
- `NEYNAR_API_KEY` for Farcaster.
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_SUBS` for Reddit.
- Telegram reader: `TG_API_ID`, `TG_API_HASH`, `TG_SESSION`, `TG_CHANNELS`.

The low-volume defaults live in `sp_config.py`; set overrides in Render only if you intentionally want different limits. Never put backend secrets in Vercel.

## Tick scheduling

Call `https://YOUR-SERVICE.onrender.com/api/cron/tick?key=YOUR_CRON_KEY` from your existing cron pinger. The tick collects sources when their intervals are due and processes a limited number of leads. The dashboard's **Run discovery cycle** queues a collection pass for the next tick. A custom search queues a Gemini-grounded public-web search for the next tick.

## API

- `POST /api/auth/login` with `{ "email": "...", "password": "..." }` — public sign-in; returns a 12-hour signed session.
- `GET /api/health`
- `GET /api/stats` — signed administrator session required
- `GET /api/leads` — signed administrator session required
- `POST /api/discovery/run` — signed administrator session required
- `POST /api/discovery/search` with `{"query":"..."}` — signed administrator session required
- `POST /api/submit` — manually queue a post/link/text
- `GET /api/cron/tick?key=...` — CRON key required
- `POST /api/telegram/webhook`

## Important limits

- Gemini grounding results depend on public indexing and Google Search coverage; it cannot guarantee comprehensive social search.
- Direct platform connectors require their own credentials, access and terms compliance.
- A Telegram channel discovered by web search is not automatically readable until you configure an authorised reader session and choose channels.
- The default X official API settings are intentionally small, but even a small API call can be billable. Keep `X_BEARER_TOKEN` blank if you do not want X API charges.
- `python -m pytest -q test_core.py` runs offline unit tests. Live platform access still needs to be tested after deployment.


## Dashboard email/password sign-in
Set these environment variables on Render (never in Vercel):
- `ADMIN_EMAIL`: the single administrator email used to sign in.
- `ADMIN_PASSWORD`: a strong, unique administrator password.
- `DASHBOARD_TOKEN`: a long random server-only signing secret (keep your existing value if it is strong; it is no longer entered in the frontend).

The frontend calls `POST /api/auth/login` and receives a signed bearer session that expires after 12 hours. Protected API routes accept only valid signed sessions. Five failed sign-in attempts from the same client IP trigger a 15-minute cooldown. Do not expose these values in `VITE_` variables or commit them to GitHub.
