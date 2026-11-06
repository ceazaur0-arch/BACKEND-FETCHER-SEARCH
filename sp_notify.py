"""Telegram messages to YOU only. Nothing is ever sent to investors or anyone else."""
import sp_config as config

ICON = {"pass": "✅", "unclear": "⚠️"}


async def send_to(chat_id, text):
    import httpx

    token = config.cfg("TG_BOT_TOKEN")
    if not token or not chat_id:
        return False
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            url,
            json={"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": True},
        )
    return r.status_code == 200


async def send_owner(text):
    return await send_to(config.cfg("TG_OWNER_ID"), text)


def format_lead(row, data):
    d = data.get("dossier") or {}
    tri = data.get("triage") or {}
    dr = data.get("draft") or {}
    ver = data.get("verification") or {}
    verdict = row.get("verdict") or "?"
    score = row.get("score")
    head = "%s %s - score %s - via %s" % (
        ICON.get(verdict, "ℹ️"),
        (row.get("kind") or "lead").upper(),
        ("%.0f" % score) if score is not None else "n/a",
        row.get("source"),
    )
    lines = [head, row.get("name") or "", d.get("summary") or tri.get("summary") or ""]
    if d.get("decision_maker"):
        lines.append("Decision maker: %s" % d["decision_maker"])
    if d.get("contact_route"):
        lines.append("Contact route: %s" % d["contact_route"])
    facts = d.get("facts") or []
    if facts:
        lines.append("Evidence:")
        for f in facts[:3]:
            lines.append("- %s\n  %s" % (f.get("claim", "")[:140], f.get("url", "")))
    if verdict == "unclear":
        lines.append("Needs a manual check: " + "; ".join((ver.get("concerns") or ["not enough independent confirmation"])[:3]))
    if dr.get("message"):
        lines.append("\nDraft (edit, then send it yourself):\n" + dr["message"])
    lines.append("\nNothing was sent. Review it in the dashboard.")
    return "\n".join(x for x in lines if x is not None)
