"""Run: python -m pytest -q test_core.py   (no network needed; the model is faked)."""
import asyncio
import json
import time

import sp_db as dbm
import sp_llm as llm
import sp_notify as notify
import sp_pipeline as pipeline
import sp_ratelimit as rl
import sp_runner as runner
import sp_safety as safety
import src_defillama
import src_x


def new_db(tmp_path):
    return dbm.Db(str(tmp_path / "t.db"))


# ---------------------------------------------------------------- rate limiter
def test_x_burst_then_ten_minute_rest():
    state, t = {}, 1000.0
    for i in range(20):
        ok, state, _ = rl.step(state, t + i * 0.5, 20, 60, 600)
        assert ok, i
    ok, state, wait = rl.step(state, t + 11, 20, 60, 600)
    assert not ok and wait == 600
    ok, state, wait = rl.step(state, t + 11 + 300, 20, 60, 600)
    assert not ok and 290 < wait < 301
    ok, state, _ = rl.step(state, t + 11 + 601, 20, 60, 600)
    assert ok and state["count"] == 1


def test_slow_calls_never_trigger_rest():
    state, t = {}, 0.0
    for i in range(50):
        ok, state, _ = rl.step(state, t + i * 61, 20, 60, 600)
        assert ok


def test_rate_limit_state_persists(tmp_path):
    db = new_db(tmp_path)
    results = [rl.acquire(db, "x", 3, 60, 600, now=100 + i)[0] for i in range(5)]
    assert results == [True, True, True, False, False]


def test_lock(tmp_path):
    db = new_db(tmp_path)
    assert dbm.lock(db, "a", 30)
    assert not dbm.lock(db, "a", 30)
    dbm.unlock(db, "a")
    assert dbm.lock(db, "a", 30)


# ---------------------------------------------------------------- safety rules
def test_scam_scan():
    hard = dict(safety.scan("Pay a listing fee first and send us your seed phrase"))
    assert hard["asks for an upfront fee"] == "hard" and hard["asks for a seed phrase"] == "hard"
    assert safety.scan("Please connect your wallet to verify")[0][1] == "soft"
    assert safety.scan("We back early Solana builders with $25k pre-seed cheques") == []


def test_score_and_domains():
    assert safety.compute_score({k: 1 for k in safety.WEIGHTS}) == 100
    assert safety.compute_score({"sector_match": 1}) == 30
    assert safety.compute_score("garbage") == 0
    assert safety.compute_score({"sector_match": 5, "stage_match": -1}) == 30  # clamped
    ds = safety.distinct_domains(["https://www.a.com/x", "https://b.a.com/y", "https://c.io", "not a url"])
    assert ds == {"a.com", "c.io"}


def test_extract_json():
    assert llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.extract_json('noise [{"a": 1}] more') == [{"a": 1}]


# ---------------------------------------------------------------- sources
def test_x_parse():
    resp = {
        "data": [{"id": "12", "text": "Open to pitches", "author_id": "u1", "public_metrics": {"like_count": 3, "retweet_count": 1}},
                 {"id": "30", "text": "x", "author_id": "u1"}],
        "includes": {"users": [{"id": "u1", "username": "fundco", "public_metrics": {"followers_count": 900}}]},
    }
    items, newest = src_x.parse(resp, "x1")
    assert newest == "30" and items[0]["url"] == "https://x.com/fundco/status/12"
    assert items[0]["key"] == "x:12"


def test_x_cooldown_from_headers():
    now = 1000.0
    assert src_x.cooldown_from_headers({"x-rate-limit-reset": "1300", "x-rate-limit-remaining": "0"}, now, 429) == 305
    assert src_x.cooldown_from_headers({"x-rate-limit-reset": "1300", "x-rate-limit-remaining": "1"}, now, 200) == 305
    assert src_x.cooldown_from_headers({"x-rate-limit-reset": "1300", "x-rate-limit-remaining": "50"}, now, 200) == 0
    assert src_x.cooldown_from_headers({}, now, 429) == 60
    assert src_x.cooldown_from_headers({"x-rate-limit-reset": "oops"}, now, 429) == 900
    assert src_x.cooldown_from_headers({"x-rate-limit-reset": "99999999", "x-rate-limit-remaining": "0"}, now, 429) == 3600


def test_defillama_aggregate():
    now = time.time()
    raises = [
        {"name": "A", "date": now - 86400, "amount": 2, "chains": ["Solana"], "leadInvestors": ["SmallFund"], "otherInvestors": [], "round": "Seed"},
        {"name": "B", "date": now - 86400 * 20, "amount": 3, "chains": ["Solana"], "leadInvestors": ["SmallFund"], "otherInvestors": ["OneOff"], "round": "Seed"},
        {"name": "C", "date": now - 86400 * 400, "amount": 3, "chains": ["Solana"], "leadInvestors": ["SmallFund"], "otherInvestors": []},
        {"name": "D", "date": now - 86400, "amount": 80, "chains": ["Solana"], "leadInvestors": ["MegaFund"], "otherInvestors": []},
        {"name": "E", "date": now - 86400, "amount": 2, "chains": ["Ethereum"], "leadInvestors": ["SmallFund"], "otherInvestors": []},
    ]
    ranked = src_defillama.aggregate(raises, now)
    assert [r[0] for r in ranked] == ["SmallFund"] and len(ranked[0][1]) == 2


# ---------------------------------------------------------------- pipeline with a fake model
def fake_model(good=True, scam_text=False):
    async def gen(prompt, *, grounded=False, json_mode=False, timeout=40, system=None):
        if "### TASK: TRIAGE" in prompt:
            return json.dumps({"relevant": True, "kind": "investor", "name": "Fund Alpha", "summary": "Seed fund", "why": "fits"}), []
        if "### TASK: PROFILE_AND_SCORE" in prompt:
            facts = [{"claim": "Led seed in LaunchX", "url": "https://fundalpha.xyz/portfolio", "date": "2026-03"},
                     {"claim": "Announced on news", "url": "https://news.example.org/a", "date": "2026-03"}]
            return json.dumps({"entity": {"name": "Fund Alpha", "site": "https://fundalpha.xyz", "type": "VC"},
                               "summary": "Active Solana seed fund", "facts": facts if good else facts[:1],
                               "decision_maker": "Jane", "contact_route": "form on site",
                               "components": {k: 0.9 for k in safety.WEIGHTS}, "red_flags": []}), [{"uri": "u", "title": "fundalpha.xyz"}]
        if "### TASK: VERIFY" in prompt:
            return json.dumps({"verdict": "pass", "independent_confirmation": True, "scam_flags": [],
                               "concerns": [], "evidence_urls": ["https://other.io/post"]}), [{"uri": "u2", "title": "news.example.org"}]
        if "### TASK: DRAFT" in prompt:
            return json.dumps({"message": "Hi Jane, saw your LaunchX seed. SPARTA is a Solana launchpad on devnet...", "short": "Hi"}), []
        raise AssertionError("unexpected prompt")
    return gen


def run_to_done(db, item, monkeypatch, gen):
    sent = []

    async def fake_send(text):
        sent.append(text)
        return True

    monkeypatch.setattr(llm, "generate", gen)
    monkeypatch.setattr(notify, "send_owner", fake_send)
    assert runner.enqueue(db, [item], 5) == 1
    for _ in range(8):
        row = runner.next_row(db, 120)
        if not row:
            break
        asyncio.run(pipeline.advance(db, row, 120))
    return db.query("SELECT * FROM leads")[0], sent


def test_full_pipeline_passes_and_drafts(tmp_path, monkeypatch):
    db = new_db(tmp_path)
    item = {"key": "x:1", "source": "x", "url": "https://x.com/a/status/1", "text": "Fund Alpha is open to pitches and funding Solana builders", "priority": 0}
    row, sent = run_to_done(db, item, monkeypatch, fake_model())
    assert row["stage"] == "done" and row["verdict"] == "pass" and row["status"] == "new"
    assert row["score"] == 90
    data = json.loads(row["data"])
    assert data["draft"]["message"].startswith("Hi Jane")
    assert len(sent) == 1 and "Nothing was sent" in sent[0]


def test_scam_text_auto_fails_and_is_hidden(tmp_path, monkeypatch):
    db = new_db(tmp_path)
    item = {"key": "x:2", "source": "x", "url": "https://x.com/b/status/2", "text": "Get funded! Pay a small listing fee first, DM me to invest funding", "priority": 0}
    row, sent = run_to_done(db, item, monkeypatch, fake_model())
    assert row["verdict"] == "fail" and row["status"] == "hidden"
    assert json.loads(row["data"]).get("draft") is None and sent == []


def test_thin_evidence_is_dropped(tmp_path, monkeypatch):
    db = new_db(tmp_path)
    item = {"key": "x:3", "source": "x", "url": "https://x.com/c/status/3", "text": "Fund Alpha grant funding open", "priority": 0}
    row, _ = run_to_done(db, item, monkeypatch, fake_model(good=False))
    assert row["verdict"] == "insufficient_evidence" and row["status"] == "hidden"


def test_keyword_prefilter_and_daily_cap(tmp_path, monkeypatch):
    db = new_db(tmp_path)
    junk = {"key": "x:9", "source": "x", "text": "gm everyone nice weather", "priority": 0}
    assert runner.enqueue(db, [junk], 5) == 0
    monkeypatch.setenv("DAILY_ITEM_CAP", "2")
    items = [{"key": "web:%d" % i, "source": "web", "text": "grant funding", "priority": 0} for i in range(5)]
    assert runner.enqueue(db, items, 5) == 2


def test_failures_retry_then_give_up(tmp_path, monkeypatch):
    db = new_db(tmp_path)

    async def boom(*a, **k):
        raise llm.LLMError("quota")

    monkeypatch.setattr(llm, "generate", boom)
    runner.enqueue(db, [{"key": "x:5", "source": "x", "text": "grant funding", "priority": 0}], 5)
    for _ in range(3):
        db.run("UPDATE leads SET next_try=0")
        asyncio.run(pipeline.advance(db, runner.next_row(db, 120), 120))
    row = db.query("SELECT * FROM leads")[0]
    assert row["stage"] == "failed" and row["status"] == "hidden"
