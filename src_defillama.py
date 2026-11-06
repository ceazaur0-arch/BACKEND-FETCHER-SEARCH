"""DefiLlama raises: free, public data on who funded what. Finds investors that recently backed
Solana projects with small rounds, so it surfaces small-cheque funds, not just mega funds."""
import time

import sp_config as config
import sp_db as dbm

URL = "https://api.llama.fi/raises"


def aggregate(raises, now, chain="solana", days=365, max_round_millions=10, min_deals=2, max_deals=25, top=12):
    cutoff = now - days * 86400
    by_inv = {}
    for r in raises or []:
        if chain not in [str(c).lower() for c in (r.get("chains") or [])]:
            continue
        date = r.get("date") or 0
        if date < cutoff:
            continue
        amount = r.get("amount")
        if amount is not None and amount > max_round_millions:
            continue
        invs = list(r.get("leadInvestors") or []) + list(r.get("otherInvestors") or [])
        for inv in invs:
            by_inv.setdefault(inv, []).append({
                "project": r.get("name"),
                "date": time.strftime("%Y-%m", time.gmtime(date)),
                "round": r.get("round"),
                "amount_m": amount,
                "category": r.get("category"),
                "source": r.get("source"),
            })
    ranked = sorted(
        ((i, d) for i, d in by_inv.items() if min_deals <= len(d) <= max_deals),
        key=lambda x: -len(x[1]),
    )
    return ranked[:top]


async def fetch(db, deadline):
    import httpx

    state = dbm.kv_get(db, "llama_state", {}) or {}
    force = bool(dbm.kv_get(db, "force_collect", 0))
    if not force and time.time() - state.get("last", 0) < config.cfgi("DEFILLAMA_INTERVAL_HOURS") * 3600:
        return []
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get(URL)
    state["last"] = time.time()
    if r.status_code != 200:
        state["error"] = "DefiLlama HTTP %s" % r.status_code
        dbm.kv_set(db, "llama_state", state)
        return []
    state.pop("error", None)
    dbm.kv_set(db, "llama_state", state)
    now = time.time()
    quarter = "%s-Q%d" % (time.strftime("%Y", time.gmtime(now)), (time.gmtime(now).tm_mon - 1) // 3 + 1)
    out = []
    for inv, deals in aggregate(r.json().get("raises"), now):
        lines = ["- %s (%s, %s, $%sM) %s" % (d["project"], d["round"], d["date"], d["amount_m"], d["source"] or "") for d in deals[:8]]
        out.append({
            "key": "llama:%s:%s" % (inv.lower(), quarter),
            "source": "defillama",
            "url": "https://defillama.com/raises",
            "text": "[hint: kind=investor] Investor %s took part in %d small Solana rounds in the last 12 months:\n%s" % (inv, len(deals), "\n".join(lines)),
            "author": inv,
            "priority": 0,
        })
    return out
