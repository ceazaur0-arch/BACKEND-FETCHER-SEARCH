"""Run: python -m pytest -q test_search.py   (no network; Gemini and Tavily are faked)."""
import asyncio
import json

import pytest

import sp_llm
import sp_llm_v2 as v2


def make_fakes(calls):
    async def fake_gemini(prompt, *, model, native_search=False, json_mode=False, timeout=40.0, system=None):
        calls.append({"model": model, "native": native_search, "json": json_mode, "prompt": prompt})
        if "You write web search queries" in prompt:
            return json.dumps({"queries": ["Fund Alpha portfolio", "Fund Alpha scam", "Fund Alpha portfolio"]}), []
        return json.dumps({"facts": [{"claim": "x", "url": "https://fundalpha.xyz/portfolio"}]}), []

    async def fake_tavily(query, *, timeout=15.0, max_results=5):
        return [
            {"title": "Portfolio", "url": "https://fundalpha.xyz/portfolio", "content": "Led seed", "date": "2026-03"},
            {"title": "Other", "url": "https://other.io/x", "content": "unrelated", "date": ""},
        ]

    return fake_gemini, fake_tavily


def test_plain_call_uses_main_model(monkeypatch):
    calls = []
    g, _ = make_fakes(calls)
    monkeypatch.setattr(v2, "_gemini", g)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    asyncio.run(sp_llm.generate("hello", json_mode=True))
    assert calls[0]["model"] == "gemini-3.5-flash-lite" and not calls[0]["native"] and calls[0]["json"]


def test_grounded_with_tavily_searches_then_answers(monkeypatch):
    calls = []
    g, t = make_fakes(calls)
    monkeypatch.setattr(v2, "_gemini", g)
    monkeypatch.setattr(v2, "_tavily", t)
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    text, sources = asyncio.run(sp_llm.generate("### TASK: VERIFY ... Fund Alpha", grounded=True))
    assert len(calls) == 2 and not any(c["native"] for c in calls)
    assert "<web_results>" in calls[1]["prompt"] and "https://other.io/x" in calls[1]["prompt"]
    # only URLs the model actually cited come back as sources
    assert sources == [{"uri": "https://fundalpha.xyz/portfolio", "title": "fundalpha.xyz"}]
    assert sp_llm.source_domains(sources) == {"fundalpha.xyz"}


def test_grounded_without_tavily_falls_back_to_native(monkeypatch):
    calls = []
    g, _ = make_fakes(calls)
    monkeypatch.setattr(v2, "_gemini", g)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_GROUNDED_MODEL", "gemini-test-grounded")
    asyncio.run(sp_llm.generate("task", grounded=True))
    assert calls == [{"model": "gemini-test-grounded", "native": True, "json": False, "prompt": "task"}]


def test_search_failure_is_reported_in_full(monkeypatch):
    calls = []
    g, _ = make_fakes(calls)

    async def boom(query, *, timeout=15.0, max_results=5):
        raise v2.LLMError("Tavily HTTP 432 (plan or key usage limit reached): out of credits")

    monkeypatch.setattr(v2, "_gemini", g)
    monkeypatch.setattr(v2, "_tavily", boom)
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    with pytest.raises(sp_llm.LLMError, match="432"):
        asyncio.run(sp_llm.generate("task", grounded=True))


def test_no_results_raises(monkeypatch):
    calls = []
    g, _ = make_fakes(calls)

    async def empty(query, *, timeout=15.0, max_results=5):
        return []

    monkeypatch.setattr(v2, "_gemini", g)
    monkeypatch.setattr(v2, "_tavily", empty)
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    with pytest.raises(sp_llm.LLMError, match="no results"):
        asyncio.run(sp_llm.generate("task", grounded=True))


def test_brave_is_backup_when_tavily_fails(monkeypatch):
    calls = []
    g, _ = make_fakes(calls)

    async def tavily_down(query, *, timeout=15.0, max_results=5):
        raise v2.LLMError("Tavily HTTP 432 (plan or key usage limit reached)")

    async def brave_ok(query, *, timeout=15.0, max_results=5):
        return [{"title": "Portfolio", "url": "https://fundalpha.xyz/portfolio", "content": "Led seed", "date": ""}]

    monkeypatch.setattr(v2, "_gemini", g)
    monkeypatch.setattr(v2, "_tavily", tavily_down)
    monkeypatch.setattr(v2, "_brave", brave_ok)
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setenv("BRAVE_API_KEY", "b")
    _, sources = asyncio.run(sp_llm.generate("task", grounded=True))
    assert sources == [{"uri": "https://fundalpha.xyz/portfolio", "title": "fundalpha.xyz"}]


def test_brave_only_and_provider_order(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "b")
    assert v2._providers() == ["brave"]
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    assert v2._providers() == ["tavily", "brave"]
    monkeypatch.setenv("SEARCH_PROVIDER", "brave")
    assert v2._providers() == ["brave", "tavily"]


def test_both_fail_reports_first_error(monkeypatch):
    calls = []
    g, _ = make_fakes(calls)

    async def bad(query, *, timeout=15.0, max_results=5):
        raise v2.LLMError("Brave HTTP 401 (key invalid)")

    monkeypatch.setattr(v2, "_gemini", g)
    monkeypatch.setattr(v2, "_brave", bad)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "b")
    with pytest.raises(sp_llm.LLMError, match="Brave HTTP 401"):
        asyncio.run(sp_llm.generate("task", grounded=True))
