"""Rules enforced in code, so the model cannot talk its way past them."""
import re
from urllib.parse import urlparse

# (pattern, label, severity). hard = auto-fail, soft = forces "needs manual check".
_RAW = [
    (r"\b(upfront|up-front|advance|registration|listing|processing|verification|due[- ]diligence|gas|unlock|activation)\s+(fee|payment|deposit)s?\b", "asks for an upfront fee", "hard"),
    (r"\bpay\s+(a\s+)?(fee|deposit)\s+(first|to (get|be|receive|unlock|list))", "pay-to-play", "hard"),
    (r"\b(seed|recovery|secret)\s+(phrase|words)\b", "asks for a seed phrase", "hard"),
    (r"\bprivate\s+key", "mentions private keys", "hard"),
    (r"\b(send|transfer|deposit)\s+[\d.,]*\s*(sol|eth|usdt|usdc|btc)\s+(first|to (receive|get|unlock|verify))", "send crypto first", "hard"),
    (r"\b(run|execute|download|install)\s+(this|our|the)\s+(script|file|app|exe|repo|package|extension)\b", "asks you to run code", "hard"),
    (r"\bdm\s+me\s+(to\s+)?(invest|get funded|get funding|claim)", "DM-first investment bait", "hard"),
    (r"\b(connect|link|sync|validate|verify)\s+(your\s+)?wallet\b", "wallet connect prompt", "soft"),
    (r"\bguaranteed\s+(returns?|profits?|roi|income)\b", "guaranteed returns", "soft"),
    (r"\b(double|triple|10x|100x)\s+your\b", "multiplier promise", "soft"),
    (r"\bclaim\s+(your\s+)?(airdrop|reward|grant)\s+(now|here)\b", "claim-now bait", "soft"),
]
SCAM_PATTERNS = [(re.compile(p, re.I), label, sev) for p, label, sev in _RAW]

HYPE = re.compile(
    r"\b(guarantee[ds]?|100x|1000x|risk[- ]free|can'?t lose|moon|once in a lifetime)\b", re.I
)

WEIGHTS = {
    "sector_match": 30,
    "stage_match": 20,
    "chain_match": 15,
    "size_match": 15,
    "recent_activity": 10,
    "reachability": 10,
}


def scan(text):
    """Return a list of (label, severity) for scam markers found in text."""
    found, seen = [], set()
    for pat, label, sev in SCAM_PATTERNS:
        if pat.search(text or "") and label not in seen:
            seen.add(label)
            found.append((label, sev))
    return found


def compute_score(components):
    """Score 0-100 from component values in 0..1. Missing components count as 0."""
    total = 0.0
    comps = components if isinstance(components, dict) else {}
    for name, weight in WEIGHTS.items():
        try:
            v = float(comps.get(name, 0))
        except (TypeError, ValueError):
            v = 0.0
        total += weight * max(0.0, min(1.0, v))
    return round(total, 1)


def is_http(url):
    return isinstance(url, str) and bool(re.match(r"^https?://[^\s]+$", url.strip(), re.I))


def domain_of(url):
    try:
        host = urlparse(url.strip()).netloc.lower().split("@")[-1].split(":")[0]
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def distinct_domains(urls):
    return {d for d in (domain_of(u) for u in urls if is_http(u)) if d}
