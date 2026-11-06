"""Settings. Everything comes from environment variables (set backend values in Render)."""
import os

DEFAULTS = {
    # core
    "DATABASE_URL": "sqlite:///sparta.db",  # production: Neon/Supabase Postgres URL
    "DASHBOARD_TOKEN": "",  # password for the dashboard (you choose it)
    "CRON_KEY": "",  # secret for the tick URL your pinger calls
    "FRONTEND_ORIGIN": "*",  # your Netlify URL once known
    # brain
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "GEMINI_URL_CONTEXT": "1",
    # telegram bot (alerts + share-to-bot)
    "TG_BOT_TOKEN": "",
    "TG_OWNER_ID": "",
    "TG_WEBHOOK_SECRET": "",
    # X official API
    "X_BEARER_TOKEN": "",
    "X_BURST": "20",  # searches allowed per window
    "X_WINDOW": "60",  # window length in seconds
    "X_REST": "600",  # rest after a burst, seconds (10 minutes)
    "X_MAX_RESULTS": "10",  # posts per search (API minimum is 10)
    "X_MAX_QUERIES_PER_RUN": "2",  # keep each scheduled X run small
    "X_DAILY_READS": "30",  # hard daily cap on posts read (controls cost)
    "X_QUERY_INTERVAL_MIN": "1440",  # each X query at most once per day
    # telegram reading (optional, uses a separate account)
    "TG_API_ID": "",
    "TG_API_HASH": "",
    "TG_SESSION": "",
    "TG_CHANNELS": "",  # comma separated public channel usernames
    "TG_INTERVAL_MIN": "360",
    # other social sources (optional)
    "NEYNAR_API_KEY": "",  # Farcaster
    "FARCASTER_INTERVAL_MIN": "360",
    "REDDIT_CLIENT_ID": "",
    "REDDIT_CLIENT_SECRET": "",
    "REDDIT_SUBS": "cryptocurrency,defi,solana,web3",
    "REDDIT_INTERVAL_MIN": "360",
    # free data
    "DEFILLAMA_INTERVAL_HOURS": "24",
    "WEB_INTERVAL_MIN": "180",
    # pipeline limits
    "SCORE_MIN": "70",
    "TICK_SECONDS": "50",
    "QUEUE_MAX": "15",
    "MAX_NEW_PER_TICK": "8",
    "DAILY_ITEM_CAP": "40",
    "MAX_ATTEMPTS": "3",
}


def cfg(name):
    return os.environ.get(name, DEFAULTS.get(name, ""))


def cfgi(name):
    try:
        return int(float(cfg(name)))
    except ValueError:
        return int(float(DEFAULTS[name]))


def cfgf(name):
    try:
        return float(cfg(name))
    except ValueError:
        return float(DEFAULTS[name])
