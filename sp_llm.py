"""Gemini calls (REST). Search grounding is switched on per call."""
import json
import re

import sp_config as config


class LLMError(Exception):
    pass


def extract_json(text):
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    opens = [(t.find(o), o, c) for o, c in (("{", "}"), ("[", "]")) if t.find(o) != -1]
    for _, o, c in sorted(opens):
        i, j = t.find(o), t.rfind(c)
        if j > i:
            try:
                return json.loads(t[i : j + 1])
            except Exception:
                continue
    raise LLMError("model did not return valid JSON")


def source_domains(sources):
    """Grounding sources come back as redirect links; the title is the site's domain."""
    out = set()
    for s in sources or []:
        title = (s.get("title") or "").strip().lower()
        if "." in title and " " not in title:
            out.add(title[4:] if title.startswith("www.") else title)
    return out


async def generate(prompt, *, grounded=False, json_mode=False, timeout=40.0, system=None):
    """Returns (text, sources). sources = [{"uri":..., "title":...}] when grounded."""
    import httpx

    key = config.cfg("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY is not set")
    model = config.cfg("GEMINI_MODEL")
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}

    def build(use_url_context):
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if grounded:
            tools = [{"google_search": {}}]
            if use_url_context:
                tools.append({"url_context": {}})
            body["tools"] = tools
        elif json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        return body

    use_ctx = config.cfg("GEMINI_URL_CONTEXT") == "1"
    async with httpx.AsyncClient(timeout=max(5.0, timeout)) as client:
        r = await client.post(url, headers=headers, json=build(use_ctx))
        if r.status_code == 400 and grounded and use_ctx:
            r = await client.post(url, headers=headers, json=build(False))
    if r.status_code != 200:
        raise LLMError("Gemini HTTP %s: %s" % (r.status_code, r.text[:200]))
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        raise LLMError("empty Gemini response (blocked or no candidates)")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    chunks = (cands[0].get("groundingMetadata") or {}).get("groundingChunks") or []
    sources = []
    for c in chunks:
        w = c.get("web") or {}
        if w.get("uri"):
            sources.append({"uri": w["uri"], "title": w.get("title", "")})
    return text, sources
