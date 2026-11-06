"""Loads your project/founder profile and the saved queries.

On Render you can override either file without redeploying code by setting the
PROFILE_JSON or QUERIES_JSON environment variable to the full JSON text.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load(env_name, filename):
    raw = os.environ.get(env_name)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return json.loads((ROOT / filename).read_text("utf-8"))


def load_profile():
    return _load("PROFILE_JSON", "profile.json")


def load_queries():
    return _load("QUERIES_JSON", "queries.json")


def keyword_ok(text):
    kws = load_queries().get("keywords", [])
    low = (text or "").lower()
    return any(k in low for k in kws)
