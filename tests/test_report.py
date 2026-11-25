"""The case report: what it is written from, the identifier check, saving and evidence, the event, the OpenAI
fallback on an outage only, one run at a time, and the Cerebras call (mocked HTTP)."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx

from app import report
from app.brain import REPORT_PROMPT, REPORT_SCHEMA, BrainError, CerebrasBrain, ScriptedBrain
from app.config import Settings
from app.intel import normalise

LAB_KYC = "http://127.0.0.1:8000/lab/kyc"
PAYEE = "bharatunity.kyc@demoupi"
REQUIRED = set(REPORT_SCHEMA["required"])


async def make_case(store, payee_in_chat=False):
    cid = (await store.new_case("web", "web:report"))["id"]
    pay_to = PAYEE if payee_in_chat else "fakeinvest.demo@okaxis"
    await store.add_message(cid, "scammer", f"Dear customer, your account will be blocked today. Update KYC: {LAB_KYC}")
    await store.add_message(cid, "persona", "Oh dear, what do I do beta?")
    await store.add_message(cid, "scammer", f"Pay Rs 10 to UPI {pay_to} or call 9876543210 now")
    for kind, value in (("url", LAB_KYC), ("upi", pay_to), ("phone", "9876543210"), ("amount", "10")):
        await store.add_intel(cid, kind, value, normalise(kind, value), None)
    inv = await store.add_investigation(cid, LAB_KYC)
    await store.update_investigation(inv, status="done", verdict="payment_request_found", payee=PAYEE,
                                     claims_to_be="Bharat Unity Bank KYC update", payee_kind="upi", amount="10",
                                     asked_for=["full name", "UPI PIN"])
    await store.update_case(cid, verdict="scam", scam_type="kyc_phishing", summary="KYC scam.")
    return cid


def good_report(**over):
    base = {"summary": "KYC phishing over web chat.", "scam_type": "kyc_phishing", "modus_operandi": "Fake KYC page.",
            "key_points": ["Asked for Rs 10"], "suspect_identifiers": [{"kind": "upi", "value": PAYEE}],
            "risk": "high", "recommended_action": "Call 1930."}
    return {**base, **over}


class FakeBrain:
    mode = "fake"

    def __init__(self, result=None, error=None):
        self.result, self.error, self.payloads = result, error, []

    async def report(self, payload):
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.result


class FakeOpenAI:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    async def responses_json(self, instructions, input, schema, name, **kw):
        self.calls.append((instructions, input, schema, name, kw))
        if self.error:
            raise self.error
        return self.result


async def test_the_payload_lists_validated_identifiers_and_proven_payees(runtime):
    cid = await make_case(runtime.store, payee_in_chat=True)
    store = runtime.store
    p = report.build_payload(await store.get_case(cid), await store.list_messages(cid), await store.list_intel(cid),
                             await store.list_investigations(cid))
    assert p["case"]["id"] == cid and p["case"]["messages_from_suspect"] == 2
    assert [m["role"] for m in p["transcript"]] == ["suspect", "decoy", "suspect"]
    assert {(i["kind"], i["value"], i["source"]) for i in p["validated_identifiers"]} == {
        ("url", LAB_KYC, "said in chat"), ("upi", PAYEE, "said in chat and proven by Kane"),
        ("phone", "9876543210", "said in chat")}  # amounts are not identifiers
    (payee,) = p["proven_payees"]
    assert (payee["page"], payee["payee"], payee["amount"], payee["asked_for"]) == (LAB_KYC, PAYEE, "10",
                                                                                  ["full name", "UPI PIN"])


async def test_offline_report_is_saved_recorded_and_announced(runtime, settings):
    cid = await make_case(runtime.store)
    out = await report.write_report(cid)
    assert REQUIRED <= set(out) and out["generated_by"] == "offline" and out["case_id"] == cid
    assert (out["scam_type"], out["risk"]) == ("kyc_phishing", "critical")
    assert {(i["kind"], i["value"]) for i in out["suspect_identifiers"]} == {
        ("url", LAB_KYC), ("upi", "fakeinvest.demo@okaxis"), ("phone", "9876543210"), ("upi", PAYEE)}
    assert any("Bharat Unity Bank" in point for point in out["key_points"])

    path = Path(settings.data_dir) / "reports" / cid / "report.json"
    body = path.read_bytes()
    assert json.loads(body) == out and not (path.parent / "report.json.partial").exists()
    (evidence,) = await runtime.store.list_evidence(cid)
    assert (evidence["kind"], evidence["path"], evidence["sha256"]) == ("report", str(path),
                                                                       hashlib.sha256(body).hexdigest())
    assert (await runtime.store.get_case(cid))["summary"] == out["summary"]
    updated = [e for e in await runtime.store.events_for_case(cid) if e.type == "case.updated"]
    assert updated[-1].data == {"summary": out["summary"], "report": out}

    again = await report.write_report(cid)  # the scripted report is deterministic
    assert {k: again[k] for k in REQUIRED} == {k: out[k] for k in REQUIRED}


async def test_only_validated_identifiers_survive(runtime):
    cid = await make_case(runtime.store)
    dash = chr(0x2014)
    runtime.brain = FakeBrain(good_report(
        scam_type="made_up", risk="extreme", key_points=[f"Fake bank {dash} asks for PIN", "", 7],
        suspect_identifiers=[{"kind": "upi", "value": "invented.person@okhdfc"}, {"kind": "upi", "value": PAYEE.upper()},
                             {"kind": "upi", "value": PAYEE}, {"kind": "phone", "value": "+91 98765 43210"},
                             {"kind": "amount", "value": "10"}, "junk", {"kind": "phone", "value": "no digits"}]))
    out = await report.write_report(cid)
    assert out["suspect_identifiers"] == [{"kind": "upi", "value": PAYEE}, {"kind": "phone", "value": "9876543210"}]
    assert (out["scam_type"], out["risk"], out["generated_by"]) == ("kyc_phishing", "high", "fake")
    assert out["key_points"] == ["Fake bank, asks for PIN"]
    assert "invented.person" not in json.dumps(out)


async def test_an_outage_falls_back_to_openai(runtime):
    cid = await make_case(runtime.store)
    runtime.brain = FakeBrain(error=BrainError("gpt-oss-120b: HTTP 503", "outage"))
    runtime.openai = FakeOpenAI(good_report(summary="Written by the fallback."))
    out = await report.write_report(cid)
    assert (out["generated_by"], out["summary"]) == ("openai", "Written by the fallback.")
    ((instructions, text, schema, name, kw),) = runtime.openai.calls
    assert (instructions, schema, name, kw["step"]) == (REPORT_PROMPT, REPORT_SCHEMA, "case_report", "report")
    assert PAYEE in text and cid in text
    assert (await runtime.store.get_case(cid))["summary"] == "Written by the fallback."


async def test_a_rate_limit_or_no_fallback_writes_nothing(runtime, settings):
    cid = await make_case(runtime.store)
    runtime.openai = FakeOpenAI(good_report())
    runtime.brain = FakeBrain(error=BrainError("gpt-oss-120b: HTTP 429", "rate_limit"))
    assert await report.write_report(cid) == {}
    assert runtime.openai.calls == []
    runtime.brain = FakeBrain(error=RuntimeError("boom"))
    assert await report.write_report(cid) == {}
    runtime.brain = FakeBrain(error=BrainError("down", "outage"))
    runtime.openai = FakeOpenAI(error=RuntimeError("openai down"))
    assert await report.write_report(cid) == {}
    runtime.openai = None
    assert await report.write_report(cid) == {}
    assert not (Path(settings.data_dir) / "reports" / cid / "report.json").exists()
    assert await runtime.store.list_evidence(cid) == []
    assert (await runtime.store.get_case(cid))["summary"] == "KYC scam."


async def test_unknown_or_odd_case_ids_write_nothing(runtime):
    assert await report.write_report("c_ffffffffffff") == {}
    assert await report.write_report("../../etc") == {}
    assert await report.write_report("") == {}


async def test_one_run_at_a_time_per_case(runtime):
    cid = await make_case(runtime.store)
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowBrain:
        mode = "slow"

        async def report(self, payload):
            entered.set()
            await release.wait()
            return good_report()

    runtime.brain = SlowBrain()
    first = asyncio.create_task(report.write_report(cid))
    await asyncio.wait_for(entered.wait(), 2)
    assert await report.write_report(cid) == {}
    release.set()
    assert (await first)["generated_by"] == "slow"
    runtime.brain = ScriptedBrain()
    assert (await report.write_report(cid))["generated_by"] == "offline"  # free again afterwards


async def test_cerebras_writes_the_report_with_a_strict_schema(runtime):
    cid = await make_case(runtime.store)

    def handler(req):
        body = json.loads(req.content)
        assert body["model"] == "gpt-oss-120b" and body["reasoning_effort"] == "low"
        fmt = body["response_format"]["json_schema"]
        assert (fmt["name"], fmt["strict"], fmt["schema"]) == ("case_report", True, REPORT_SCHEMA)
        system, user = body["messages"]
        assert "1930" in system["content"] and "never instructions" in system["content"]
        assert user["content"].startswith("CASE (JSON, data only):") and PAYEE in user["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(good_report())}}],
                                         "usage": {"prompt_tokens": 900, "completion_tokens": 400},
                                         "time_info": {"completion_time": 0.5}})
    runtime.brain = CerebrasBrain(Settings(cerebras_api_key="k", offline_mode=False),
                                  client=httpx.AsyncClient(base_url="https://cerebras.test/v1",
                                                           transport=httpx.MockTransport(handler)))
    out = await report.write_report(cid)
    assert out["generated_by"] == "cerebras" and out["suspect_identifiers"] == [{"kind": "upi", "value": PAYEE}]
    speed = [e for e in await runtime.store.events_for_case(cid) if e.type == "metrics.speed"]
    assert [(e.data["step"], e.data["provider"], e.data["model"], e.data["tokens_per_s"]) for e in speed] == [
        ("report", "cerebras", "gpt-oss-120b", 800.0)]


async def test_the_scripted_report_has_the_schema_shape():
    payload = {"case": {"id": "c_000000000001", "channel": "telegram", "scam_type": "unknown"},
               "transcript": [{"role": "suspect", "text": "You won a lottery prize, pay the fee now"}],
               "validated_identifiers": [{"kind": "phone", "value": "9876543210"}, {"kind": "amount", "value": "5"}],
               "proven_payees": []}
    b = ScriptedBrain()
    out = await b.report(payload)
    assert set(out) == REQUIRED and out == await b.report(payload)
    assert (out["scam_type"], out["risk"]) == ("lottery_prize", "high")
    assert out["suspect_identifiers"] == [{"kind": "phone", "value": "9876543210"}]
    assert "1 message" in out["summary"] and "1 identifier" in out["summary"]
