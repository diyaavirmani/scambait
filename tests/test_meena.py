"""Meena: the guard, her prompt, the scripted lines, and the Cerebras client (mocked HTTP), its errors and speed."""
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
    text, flags = guard("Oh dear " + chr(0x2014) + " wait. " + "I am confused. " * 40)
    assert len(text) <= meena.MAX_REPLY + 3 and chr(0x2014) not in text


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


async def test_every_cerebras_call_reports_its_speed(runtime):
    def handler(req):
        if json.loads(req.content)["model"] == "qwen-3.8-27b":
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps({"is_scam": True, "p_scam": 0.9, "scam_type": "other",
                                                                "risk": "high"})}}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 50}, "time_info": {"completion_time": 0.25}})
        return completion({"reply": "Who is this, beta?", "summary": ""})
    b = brain_with(handler)
    await b.flag([{"role": "scammer", "text": "KYC"}], "c_000000000001")
    await b.reply(Context(history=[{"role": "scammer", "text": "hi"}]))
    flag, reply = [e for e in await runtime.store.events_after(0) if e.type == "metrics.speed"]
    assert flag.case_id == "c_000000000001"
    assert {k: flag.data[k] for k in ("step", "provider", "model", "tokens_per_s")} == {
        "step": "flag", "provider": "cerebras", "model": "qwen-3.8-27b", "tokens_per_s": 200.0}
    assert (reply.data["step"], reply.data["model"], "tokens_per_s" in reply.data) == ("reply", "gpt-oss-120b", False)
    assert isinstance(flag.data["ms"], int)


async def test_brain_errors_say_what_went_wrong(monkeypatch):
    import app.brain as brain_mod

    async def no_sleep(_):
        return None
    monkeypatch.setattr(brain_mod.asyncio, "sleep", no_sleep)

    def refused(req):
        raise httpx.ConnectError("refused", request=req)
    for handler, kind in ((lambda req: httpx.Response(429), "rate_limit"), (lambda req: httpx.Response(503), "outage"),
                          (refused, "outage"), (lambda req: httpx.Response(401), "http"),
                          (lambda req: completion(["not", "an", "object"]), "bad_output")):
        with pytest.raises(BrainError) as info:
            await brain_with(handler).reply(Context(history=[]))
        assert info.value.kind == kind
    assert BrainError("plain").kind == "error"


async def test_self_test_checks_models():
    ok = brain_with(lambda req: httpx.Response(200, json={"data": [{"id": "gpt-oss-120b"}, {"id": "qwen-3.8-27b"}]}))
    assert (await ok.self_test())["ok"] is True
    with pytest.raises(BrainError):
        await brain_with(lambda req: httpx.Response(200, json={"data": [{"id": "gpt-oss-120b"}]})).self_test()


@pytest.mark.parametrize("text,used", [
    ("My grandson says it is Bharat Unity Bank and wants Rs 10", True),
    ("Bharat Unity wants 10 rupees, whose name will show?", True),
    ("It wants 1,280 rupees", True),
    ("My grandson says it is Bharat Unity Bank and wants money", False),
    ("It wants Rs 10 only, whose name will show?", False),
    ("It says some bank wants 10 rupees", False),
    ("Bharat Unity Bank wants 100 rupees", False),
    ("Oh dear, my glasses are blurry", False),
])
def test_mentions_finding(text, used):
    inv = {"claims_to_be": "Bharat Unity Bank", "amount": "10"} if "1,280" not in text else {"amount": "1280"}
    assert meena.mentions_finding(text, inv) is used


def test_a_link_turn_has_its_own_strategy_and_can_insist():
    inv = {"claims_to_be": "Bharat Unity Bank", "amount": "10", "payee": "x@demoupi", "payee_kind": "upi"}
    ctx = Context(history=[{"role": "scammer", "text": "pay now"}], findings=[inv])
    system = persona_messages(ctx)[0]["content"]
    assert "do not ask them to repeat" in system and "last draft" not in system
    import dataclasses
    system = persona_messages(dataclasses.replace(ctx, insist=True))[0]["content"]
    assert "Bharat Unity Bank and asks for Rs 10" in system
