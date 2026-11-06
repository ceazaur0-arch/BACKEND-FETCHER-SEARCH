"""Burst limiter that survives serverless restarts (state lives in the database).

Default for X: up to 20 searches in a 60 second window, then a 10 minute rest.
"""
import time

import sp_db as dbm


def step(state, now, burst, window, rest):
    """Pure function. Returns (allowed, new_state, seconds_to_wait)."""
    s = dict(state or {})
    rest_until = s.get("rest_until", 0)
    if now < rest_until:
        return False, s, rest_until - now
    if rest_until and now >= rest_until:
        s = {}  # rest is over, start a fresh window
    ws = s.get("window_start")
    if ws is None or now - ws >= window:
        s = {"window_start": now, "count": 0, "rest_until": 0}
    if s["count"] >= burst:
        s["rest_until"] = now + rest
        return False, s, rest
    s["count"] += 1
    return True, s, 0


def acquire(db, name, burst, window, rest, now=None):
    now = time.time() if now is None else now
    state = dbm.kv_get(db, "rl:" + name, {})
    ok, new, wait = step(state, now, burst, window, rest)
    dbm.kv_set(db, "rl:" + name, new)
    return ok, wait
