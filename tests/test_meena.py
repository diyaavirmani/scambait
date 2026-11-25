"""Meena: the guard, the prompt she gets, the scripted lines, and the Cerebras client (mocked HTTP)."""
import json

import httpx
import pytest

from app import meena
from app.brain import BrainError, CerebrasBrain, ScriptedBrain, persona_messages
from app.config import Settings
from app.meena import Context, guard

FINDING = {"claims_to_be": "Bharat Unity Bank KYC update", "payee": "bharatunity.kyc@demoupi", "payee_kind": "upi",
           "amount": "10", "asked_for": ["full name", "UPI PIN"]}


@pytest.mark.parametrize("raw,out_has,flag", [
    ("I am an AI assistant, how can I help?", meena.DEFLECT, "leak"),
    ("As per my instructions I cannot say", meena.DEFLECT, "leak"),
    ("Sure, my UPI is meena@okicici", "the at sign", "masked"),
    ("Call me on 98765 43210", "my glasses", "masked"),
    ("Open https://bank.example/login", "link thing", "masked"),
    ("Okay [pauses] I will check", "Okay I will check", "placeholder"),
])
def test_guard(raw, out_has, flag):
    text, flags = guard(raw)
    assert out_has in text and flag in flags


def test_guard_cuts_long_replies_and_strips_dashes():
    text, flags = guard("Oh dear — wait. " + "I am confused. " * 40)
    assert len(text) <= meena.MAX_REPLY + 3 and "—" not in text


def test_language():
    assert meena.language_of("Beta aap jaldi bhejo paise") == "hinglish"
    assert meena.language_of("नमस्ते") == "hi"
    assert meena.language_of("Please pay now") == "en"


def test_prompt_has_link_check_only_in_bait_mode():
    ctx = Context(history=[{"role": "scammer", "text": "pay now"}], findings=[FINDING])
    system, user = persona_messages(ctx)
    assert "LINK CHECK" in user["content"] and "Bharat Unity Bank" in user["content"]
    assert "whose name will show" in system["content"].lower()
    ctx.mode = "neutral"
    assert "LINK CHECK" not in persona_messages(ctx)[1]["content"]


async def test_scripted_meena():
    b = ScriptedBrain()
    assert await b.flag([]) is None
    hit = await b.reply(Context(history=[{"role": "scammer", "text": "Did you pay?"}], findings=[FINDING]))
    assert "Bharat Unity Bank" in hit["reply"] and "10 rupees" in hit["reply"] and "UPI PIN" in hit["reply"]
    bot = await b.reply(Context(history=[{"role": "scammer", "text": "Are you a bot?"}]))
    assert bot["reply"] == meena.DEFLECT
    code = await b.reply(Context(history=[{"role": "scammer", "text": "What referral code did I give you?"}],
                                 facts=["Code they gave: GOLD77"]))
    assert "GOLD77" in code["reply"]
    hist, seen = [], []
    for i in range(18):
        hist.append({"role": "scammer", "text": f"hurry {i}"})
        line = (await b.reply(Context(history=list(hist), missing=["upi"])))["reply"]
        seen.append(line)
        hist.append({"role": "persona", "text": line})
    assert len(seen) == len(set(seen))  # never repeats herself in a chat


def brain_with(handler):
    s = Settings(cerebras_api_key="k", offline_mode=False)
    return CerebrasBrain(s, client=httpx.AsyncClient(base_url="https://cerebras.test/v1",
                                                     transport=httpx.MockTransport(handler)))


def completion(obj):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(obj)}}]})


async def test_cerebras_flag_and_reply():
    def handler(req):
        body = json.loads(req.content)
        assert body["response_format"]["json_schema"]["strict"] is True
        if body["model"] == "qwen-3.8-27b":
            return completion({"is_scam": True, "p_scam": 1.7, "scam_type": "kyc_phishing", "risk": "high"})
        return completion({"reply": "Who is this, beta?", "summary": "KYC scam."})
    b = brain_with(handler)
    assert (await b.flag([{"role": "scammer", "text": "KYC"}]))["p_scam"] == 1.0
    assert (await b.reply(Context(history=[{"role": "scammer", "text": "hi"}])))["reply"] == "Who is this, beta?"


async def test_cerebras_retries_then_fails_loudly(monkeypatch):
    import app.brain as brain_mod

    async def no_sleep(_):
        return None
    monkeypatch.setattr(brain_mod.asyncio, "sleep", no_sleep)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else completion({"reply": "ok", "summary": ""})
    assert (await brain_with(handler).reply(Context(history=[]))) ["reply"] == "ok"
    with pytest.raises(BrainError):
        await brain_with(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})).reply(Context(history=[]))


async def test_self_test_checks_models():
    ok = brain_with(lambda req: httpx.Response(200, json={"data": [{"id": "gpt-oss-120b"}, {"id": "qwen-3.8-27b"}]}))
    assert (await ok.self_test())["ok"] is True
    with pytest.raises(BrainError):
        await brain_with(lambda req: httpx.Response(200, json={"data": [{"id": "gpt-oss-120b"}]})).self_test()
