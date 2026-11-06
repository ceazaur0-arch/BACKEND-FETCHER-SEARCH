# SPARTA agents - backend (Render)

Finds and checks investors, grants, buyers, jobs and partners for SPARTA, then **drafts** messages for you.
It never sends anything to anyone but you (a Telegram message to your own bot).

## How it works
A free pinger calls one URL every 1-2 minutes (a "tick"). Each tick:
1. Pulls new items from the sources: DefiLlama raises (free), Google-grounded web search, and optionally X (official API), Telegram channels, Farcaster, Reddit.
2. Runs each item through four agents, one resumable step at a time: **Triage -> Profiler+Scorer -> Verifier -> Drafter**.
3. Messages you on Telegram only for leads that passed. Everything else stays hidden or under "Needs check".

The pinger also keeps Render's free service awake. All state (queue, rate limits, cursors) lives in your Postgres, so a restart loses nothing.

**Rules enforced in code, not just in prompts:**
- Every claim needs a source URL or it is thrown away. Fewer than 2 sourced claims = dropped.
- Score below 70 = dropped. Scam markers (upfront fees, seed phrase, "run our code", DM-first bait) = auto-fail. Weak markers or fewer than 2 independent sources = "Needs check", no draft.
- The Verifier is a separate call that never sees the score and tries to disprove the lead.
- Text from posts is treated as untrusted data, never as instructions.

**X is optional.** With no `X_BEARER_TOKEN` it is skipped. If you add one: 20 searches a minute, then a 10 minute rest (`X_BURST`, `X_WINDOW`, `X_REST`), a daily cap on posts read (`X_DAILY_READS`), and it backs off by itself when X's rate-limit headers say it is nearly out, and messages you if X pauses it. **Share-to-bot** is the free way to use X: share any post or link to your bot.

## Setup from a phone (about 40 minutes, all free tiers)

### 1. Database
Create a project at neon.tech and copy the **pooled connection string** (starts with `postgresql://`). That is `DATABASE_URL`. (Do not use Render's free Postgres: it expires.)

### 2. Gemini key
At aistudio.google.com create an API key. That is `GEMINI_API_KEY`. The free tier has low limits, so `DAILY_ITEM_CAP` is preset to 15.
The default model is `gemini-2.5-flash`. If Google has retired that name, set `GEMINI_MODEL` to the current Flash model.

### 3. Telegram bot
In Telegram message @BotFather, send `/newbot`, copy the token. That is `TG_BOT_TOKEN`.

### 4. Put the code on GitHub
Create a private repo on github.com. Unzip `sparta-backend.zip` on your phone and use **Add file -> Upload files** to upload every file. All files sit at the top level, so no folders to fight with.

### 5. Deploy on Render
Render -> New -> **Web Service** -> connect your GitHub repo.
- Runtime: **Python 3**
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn sp_main:app --host 0.0.0.0 --port $PORT`
- Instance type: **Free**
- Add environment variables (see `.env.example`): `DATABASE_URL`, `GEMINI_API_KEY`, `TG_BOT_TOKEN`, `DASHBOARD_TOKEN` (a long password you make up), `CRON_KEY` (another long secret), `TG_WEBHOOK_SECRET` (a random string), `DAILY_ITEM_CAP` = `15`.

Deploy. Open `https://YOUR-SERVICE.onrender.com/api/health`. You should see `{"ok":true}`. (The first load after idle can take about a minute.)

### 6. Connect the bot
Open `https://YOUR-SERVICE.onrender.com/api/telegram/setup?key=YOUR_CRON_KEY` once. Send `/start` to your bot: it replies with your chat id. Add it as `TG_OWNER_ID` in Render's Environment (the service restarts). Now only you can use the bot.

### 7. Start the ticks (free pinger)
At cron-job.org create a job that opens
`https://YOUR-SERVICE.onrender.com/api/cron/tick?key=YOUR_CRON_KEY`
every 2 minutes. It replies instantly and the work runs after, so the pinger never times out. Overlapping ticks are skipped safely. To see a tick's result once, add `&wait=1`.
Render's free tier sleeps after about 15 minutes with no traffic and has a monthly hours allowance. Pinging every 2 minutes keeps it awake. Check Render's current free-tier rules, because they change.

### 8. Frontend
Deploy `sparta-frontend.zip` on Netlify (its README explains). In its Settings paste your Render link and `DASHBOARD_TOKEN`. Then set `FRONTEND_ORIGIN` on Render to your Netlify link.

### Share-to-bot
Any X post, link or text you share or forward to your bot is queued with top priority. You get the verdict and a draft in Telegram when it is done.
`/search` runs every source on the next tick. `/status` shows queue and X usage. `/leads` shows the top verified leads.

## Optional sources
- **X:** `X_BEARER_TOKEN` (paid, pay-per-use).
- **Telegram channels:** `TG_API_ID`, `TG_API_HASH` (my.telegram.org), `TG_CHANNELS` (public channel usernames, comma separated) and `TG_SESSION` (run `make_tg_session.py` once, in Google Colab if you have no PC). Use a **spare** Telegram account. A single always-on Render server is a good fit for this.
- **Farcaster:** `NEYNAR_API_KEY`. **Reddit:** `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_SUBS` (Reddit may need to approve the app).

## Change what it searches
Edit `queries.json` (X queries, Farcaster, Reddit, web tasks, keywords) and `profile.json` (SPARTA and your background; add your GitHub link and any traction - the drafter will not claim anything that is empty). Or set `QUERIES_JSON` / `PROFILE_JSON` in Render to override without touching code.

## Be honest about the limits
- I tested the logic offline (rate limiter, X back-off, scoring, scam filter, the whole pipeline with a fake model): 15 tests pass. I could **not** run it against real Gemini, X, Telegram, Neynar, Reddit or Render from here, so expect a small round of fixes on first deploy. Send the error text and it can be fixed.
- Response formats from X, Neynar and Reddit can change; the parsers are defensive but unverified live.
- Nothing here makes outreach safe by itself. Send few, personal messages from your own account, never pay anyone to get funded, never share a seed phrase, and check the law for token fundraising where you are.

## Files
`sp_main.py` API, `sp_runner.py` tick loop, `sp_pipeline.py` agents and rules, `sp_safety.py` scam and scoring rules, `sp_ratelimit.py` X burst limiter, `src_*.py` sources, `sp_tgbot.py` your bot, `render.yaml` optional Render blueprint, `test_core.py` tests (`python -m pytest -q test_core.py`).
